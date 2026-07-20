<?php

namespace Mautic\CoreBundle\Controller;

use Mautic\CoreBundle\CoreEvents;
use Mautic\CoreBundle\Event\GlobalSearchEvent;
use Symfony\Component\HttpFoundation\Request;

/**
 * Almost all other Mautic Bundle controllers extend this default controller.
 */
class DefaultController extends CommonController
{
    /**
     * @return \Symfony\Component\HttpFoundation\RedirectResponse|\Symfony\Component\HttpFoundation\Response
     */
    public function indexAction(Request $request)
    {
        $root = $this->coreParametersHelper->get('webroot');

        if (empty($root)) {
            return $this->redirectToRoute('mautic_dashboard_index');
        }
        /** @var \Mautic\PageBundle\Model\PageModel $pageModel */
        $pageModel = $this->getModel('page');
        $page      = $pageModel->getEntity($root);

        if (empty($page)) {
            return $this->notFound();
        }

        $slug = $pageModel->generateSlug($page);

        $request->attributes->set('ignore_mismatch', true);

        return $this->forward('Mautic\PageBundle\Controller\PublicController::indexAction', ['slug' => $slug]);
    }

    public function globalSearchAction(Request $request): \Symfony\Component\HttpFoundation\Response
    {
        $searchStr = $request->get('global_search', $request->getSession()->get('mautic.global_search', ''));
        $request->getSession()->set('mautic.global_search', $searchStr);

        if (!empty($searchStr)) {
            $event = new GlobalSearchEvent($searchStr, $this->translator);
            $this->dispatcher->dispatch($event, CoreEvents::GLOBAL_SEARCH);
            $results = $event->getResults();
        } else {
            $results = [];
        }

        return $this->render('@MauticCore/GlobalSearch/globalsearch.html.twig',
            [
                'results'      => $results,
                'searchString' => $searchStr,
            ]
        );
    }

    public function notificationsAction(): \Symfony\Component\HttpFoundation\Response
    {
        /** @var \Mautic\CoreBundle\Model\NotificationModel $model */
        $model = $this->getModel('core.notification');

        [$notifications, $showNewIndicator, $updateMessage] = $model->getNotificationContent(null, false, 200);

        return $this->delegateView(
            [
                'contentTemplate' => '@MauticCore/Notification/notifications.html.twig',
                'viewParameters'  => [
                    'showNewIndicator' => $showNewIndicator,
                    'notifications'    => $notifications,
                    'updateMessage'    => $updateMessage,
                ],
            ]
        );
    }

    /**
     * CSTS: 语言切换器。Mautic 7.x 移除了全局 mautic_core_switch_locale 路由，这里重新实现——
     * 更新当前用户 locale 并即时刷新 session，跳回来源页（就地切换，不跳转到账户/系统目录）。
     */
    public function switchLocaleAction(Request $request, string $language): \Symfony\Component\HttpFoundation\RedirectResponse
    {
        $supported = ['en_US', 'zh_CN'];
        if (!in_array($language, $supported, true)) {
            $language = $this->coreParametersHelper->get('locale', 'zh_CN');
        }

        $user = $this->getUser();
        if ($user instanceof \Mautic\UserBundle\Entity\User) {
            $user->setLocale($language);
            /** @var \Mautic\UserBundle\Model\UserModel $userModel */
            $userModel = $this->getModel('user');
            $userModel->saveEntity($user);
        }

        // 立即更新 session，使当前会话后续请求即时生效（无需重新登录）
        $request->getSession()->set('_locale', $language);

        // 回到来源页（就地切换语言，不跳转到系统目录）
        $referer = $request->headers->get('referer');
        if (empty($referer)) {
            $referer = $this->generateUrl('mautic_dashboard_index');
        }

        return $this->redirect($referer);
    }
}
