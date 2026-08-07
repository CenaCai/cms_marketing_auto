<?php

declare(strict_types=1);

/**
 * 结构一致性校验：逐表比对 Mautic 源库与 automarket_tp8 的列定义。
 *
 * 用法：php scripts/schema_diff.php
 * 退出码：0 = 完全一致（允许白名单差异）；1 = 存在差异
 */

$src = new PDO('mysql:host=127.0.0.1;port=3306;dbname=mautic;charset=utf8mb4', 'mautic', 'mautic', [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
]);
$dst = new PDO('mysql:host=127.0.0.1;port=3306;dbname=automarket_tp8;charset=utf8mb4', 'mautic', 'mautic', [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
]);

$tables = [
    'categories', 'users', 'lead_fields', 'stages', 'lead_tags',
    'leads', 'lead_tags_xref', 'lead_lists', 'lead_lists_leads',
];

/** 允许的差异：新库有意新增的列 */
$allowedExtra = [
    'users'      => ['uuid'],
    'categories' => [],
];

$describe = static function (PDO $pdo, string $table): array {
    $rows = $pdo->query("SHOW COLUMNS FROM `{$table}`")->fetchAll(PDO::FETCH_ASSOC);
    $out  = [];
    foreach ($rows as $r) {
        $out[$r['Field']] = sprintf(
            '%s|null=%s|default=%s|extra=%s',
            strtolower($r['Type']),
            $r['Null'],
            $r['Default'] ?? 'NULL',
            strtolower($r['Extra'])
        );
    }

    return $out;
};

$hasDiff = false;

foreach ($tables as $table) {
    $a = $describe($src, $table);
    $b = $describe($dst, $table);

    $missing = array_diff_key($a, $b);                       // 源有目标无
    $extra   = array_diff_key($b, $a);                       // 目标有源无
    $extra   = array_diff_key($extra, array_flip($allowedExtra[$table] ?? []));

    $changed = [];
    foreach (array_intersect_key($a, $b) as $col => $def) {
        if ($def !== $b[$col]) {
            $changed[$col] = ['src' => $def, 'dst' => $b[$col]];
        }
    }

    if ($missing === [] && $extra === [] && $changed === []) {
        printf("  [OK]   %-18s %d 列\n", $table, count($a));
        continue;
    }

    $hasDiff = true;
    printf("  [DIFF] %s\n", $table);

    foreach (array_keys($missing) as $col) {
        printf("         - 目标库缺列: %s (%s)\n", $col, $a[$col]);
    }
    foreach (array_keys($extra) as $col) {
        printf("         + 目标库多列: %s (%s)\n", $col, $b[$col]);
    }
    foreach ($changed as $col => $d) {
        printf("         ~ %s\n             源: %s\n             目标: %s\n", $col, $d['src'], $d['dst']);
    }
}

echo $hasDiff ? "\n结果：存在结构差异\n" : "\n结果：全部一致\n";

exit($hasDiff ? 1 : 0);
