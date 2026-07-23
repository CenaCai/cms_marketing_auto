<?php
// 一次性导入旅游 B2B/B2C 客户标签库到 Mautic lead_tags 表
// 标签名原样保留；分类层级写入 description 前缀，便于在标签库与管理界面查看上下文。

$src = 'C:/Users/cenacai/Downloads/travel_customer_tags.txt';
if (!is_file($src)) { die("SOURCE NOT FOUND: $src\n"); }

$raw = file($src, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
if ($raw === false) { die("cannot read $src\n"); }

$section  = '';   // B2B / B2C
$subtype  = '';   // 静态标签 / 动态标签 / 生命周期标签 / 跨品类偏好标签
$category = '';   // 当前分类（企业资质类型 等）
$rows     = [];

function stripStar($s) {
    return trim(str_replace('**', '', $s));
}
function cleanSub($s) {
    // 去掉 "1. " 前缀与 "（...）" 后缀
    $s = preg_replace('/^\d+\.\s*/', '', $s);
    $s = preg_replace('/（.*?）/u', '', $s);
    return trim($s);
}

foreach ($raw as $line) {
    $line = trim($line);
    if ($line === '') continue;

    if (strpos($line, 'B2B 客户标签') !== false) { $section = 'B2B'; continue; }
    if (strpos($line, 'B2C 客户标签') !== false) { $section = 'B2C'; continue; }

    if (strpos($line, '### ') === 0) {
        $subtype = cleanSub(ltrim(substr($line, 4)));
        continue;
    }

    if (strpos($line, '|') === 0) {
        if (strpos($line, ':---') !== false) continue;           // 分隔行
        // 仅去掉首尾管道符，保留中间空列（续行首列为空）
        $inner = trim($line, '|');
        $parts = array_map('trim', explode('|', $inner));
        if (empty($parts)) continue;
        if ($parts[0] === '标签分类') continue;                  // 表头
        if (count($parts) < 3) continue;                         // 非数据行

        $cat  = stripStar($parts[0]);
        $name = stripStar($parts[1]);
        $desc = implode('|', array_slice($parts, 2));            // 描述若含 | 也安全
        if ($cat !== '')  $category = $cat;
        if ($name === '') continue;
        $rows[] = [
            'section'  => $section,
            'subtype'  => $subtype,
            'category' => $category,
            'name'     => $name,
            'desc'     => $desc,
        ];
    }
}

// 按 tag 名去重（文件内可能重复则取首次）
$uniq = [];
foreach ($rows as $r) {
    if (!isset($uniq[$r['name']])) $uniq[$r['name']] = $r;
}
$rows = array_values($uniq);

// 连接 DB
$pdo = new PDO('mysql:host=localhost;port=3306;dbname=mautic', 'mautic', 'mautic');
$existing = $pdo->query('SELECT tag FROM lead_tags')->fetchAll(PDO::FETCH_COLUMN);
$existingLower = array_map('mb_strtolower', $existing);

$created = 0; $skipped = 0;
$ins = $pdo->prepare('INSERT INTO lead_tags (tag, description, uuid) VALUES (?, ?, UUID())');
foreach ($rows as $r) {
    if (in_array(mb_strtolower($r['name']), $existingLower, true)) {
        $skipped++;
        echo "SKIP (exists): {$r['name']}\n";
        continue;
    }
    $prefix = "[{$r['section']} · {$r['subtype']} · {$r['category']}] ";
    $ins->execute([$r['name'], $prefix . $r['desc']]);
    $created++;
    echo "ADD: {$r['name']}\n";
}

echo "\nTOTAL unique={".count($rows)."} created={$created} skipped={$skipped}\n";
echo "DONE\n";
