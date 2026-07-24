<?php
/**
 * Repair script-created emails so the GrapesJS canvas builder opens with content.
 *
 * Root cause (two parts):
 *  1. The GrapesJS builder reads the design ONLY from `content['grapesjsbuilder']['editorState']`
 *     (the `.builder-json` field), never from `custom_html`. Script-created emails had an empty
 *     `content` (a:0:{}), so the builder had nothing to load.
 *  2. On page load for an EXISTING email, Mautic does NOT run `setThemeHtml` (that only fires for
 *     new emails or when a theme is clicked). So the `.builder-html` textarea is filled directly
 *     from `custom_html`. The JS `getOriginalContentHtml()` REQUIRES `custom_html` to be a complete
 *     HTML document (non-empty <head> AND <body>), otherwise it throws "No valid HTML template found"
 *     and the canvas never initializes. Script-created emails stored only an HTML *fragment*.
 *
 * Fix:
 *  - Seed a valid `editorState` whose page-frame `component` is the email's HTML fragment.
 *  - Rewrite `custom_html` as a FULL HTML document by rendering the HTML-mode theme `blank_html`
 *    (which has {{ content }} in the body slot) with the fragment injected — matching the document
 *    shape Mautic's own builder-save produces.
 *  - Point the email at the `blank_html` HTML-mode theme.
 *
 * Idempotent: skips re-seeding editorState if present; only upgrades custom_html when it is still
 * a fragment; only writes when something actually changed.
 */

declare(strict_types=1);

require_once __DIR__.'/vendor/autoload.php';
require_once __DIR__.'/app/AppKernel.php';

$kernel = new \AppKernel('prod', false);
$kernel->boot();
$container = $kernel->getContainer();

/** @var \Mautic\EmailBundle\Model\EmailModel $model */
$model = $container->get('mautic.email.model.email');
/** @var \Mautic\CoreBundle\Helper\ThemeHelper $themeHelper */
$themeHelper = $container->get('mautic.helper.theme');

$ids   = [4, 5, 7, 8];
$theme = 'blank_html';

// Resolve the theme's HTML template logical name (no MJML twin -> HTML mode).
$htmlLogical = $themeHelper->checkForTwigTemplate('@themes/'.$theme.'/html/email.html.twig');

foreach ($ids as $id) {
    /** @var \Mautic\EmailBundle\Entity\Email|null $email */
    $email = $model->getEntity($id);
    if (null === $email || (int) $email->getId() !== (int) $id) {
        echo "SKIP id={$id}: not found\n";
        continue;
    }

    $fragment = $email->getCustomHtml();
    if (!is_string($fragment) || '' === trim(strip_tags($fragment))) {
        echo "SKIP id={$id} ({$email->getName()}): custom_html empty, nothing to seed\n";
        continue;
    }

    $changed = false;

    // --- Part 1: ensure custom_html is a COMPLETE HTML document (head + body) ---
    $isFullDoc = stripos($fragment, '<head') !== false && stripos($fragment, '<body') !== false;
    if (!$isFullDoc) {
        $fullDoc = $themeHelper->renderThemeTemplate(
            $htmlLogical,
            [
                'isNew'     => false,
                'content'   => $fragment,
                'email'     => $email,
                'template'  => $theme,
                'basePath'  => '',
            ]
        );
        if (stripos($fullDoc, '<head') !== false && stripos($fullDoc, '<body') !== false) {
            $email->setCustomHtml($fullDoc);
            $changed = true;
            echo "FIX  id={$id} ({$email->getName()}): custom_html upgraded to full HTML document (".strlen($fullDoc)." bytes)\n";
        } else {
            echo "WARN id={$id} ({$email->getName()}): theme render did not produce a full document, left custom_html as-is\n";
        }
    } else {
        echo "OK   id={$id} ({$email->getName()}): custom_html already a full document\n";
    }

    // --- Part 2: ensure editorState exists in content ---
    $existing = $email->getContent();
    $hasState = isset($existing['grapesjsbuilder']['editorState'])
        && is_array($existing['grapesjsbuilder']['editorState'])
        && !empty($existing['grapesjsbuilder']['editorState']);
    if (!$hasState) {
        $editorState = [
            'assets'     => [],
            'styles'     => [],
            'pages'      => [
                [
                    'frames' => [
                        [
                            'component' => $fragment,
                            'id'       => 'main',
                        ],
                    ],
                    'type' => 'main',
                    'id'   => 'main',
                ],
            ],
            'symbols'     => [],
            'dataSources' => [],
        ];
        $newContent = [
            'grapesjsbuilder' => [
                'editorState' => $editorState,
                'updatedAt'   => (new \DateTime('now', new \DateTimeZone('UTC')))->format(\DateTime::ATOM),
            ],
        ];
        $email->setContent($newContent);
        $changed = true;
        echo "FIX  id={$id} ({$email->getName()}): seeded editorState (".strlen(serialize($newContent))." bytes)\n";
    } else {
        echo "OK   id={$id} ({$email->getName()}): editorState already present\n";
    }

    // --- Part 3: ensure template points at the HTML-mode theme ---
    if ((string) $email->getTemplate() !== $theme) {
        $email->setTemplate($theme);
        $changed = true;
        echo "FIX  id={$id} ({$email->getName()}): template -> {$theme}\n";
    }

    if ($changed) {
        $model->saveEntity($email);
        echo "SAVE id={$id} ({$email->getName()})\n";
    } else {
        echo "NOCHANGE id={$id} ({$email->getName()})\n";
    }
}

echo "Done.\n";
