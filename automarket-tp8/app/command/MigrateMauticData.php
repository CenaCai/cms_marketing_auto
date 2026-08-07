<?php

declare(strict_types=1);

namespace app\command;

use think\console\Command;
use think\console\Input;
use think\console\input\Option;
use think\console\Output;
use think\facade\Db;
use Throwable;

/**
 * Mautic 生产数据 -> automarket_tp8 迁移（ETL）
 *
 * 用法：
 *   php think etl:mautic                 全量迁移（保留原始主键）
 *   php think etl:mautic --truncate      迁移前清空目标表
 *   php think etl:mautic --table=leads   只迁某张表
 *   php think etl:mautic --dry-run       只统计不写库
 *
 * 关键转换：
 *   1. Mautic 用 PHP serialize() 存 array 字段，新库统一改 JSON；
 *   2. leads.generated_email_domain 是生成列，必须排除；
 *   3. 保留原始 ID，迁完重置 AUTO_INCREMENT。
 */
class MigrateMauticData extends Command
{
    /** 迁移顺序 = 外键依赖顺序 */
    private const TABLES = [
        'categories',
        'users',
        'lead_fields',
        'stages',
        'lead_tags',
        'leads',
        'lead_tags_xref',
        'lead_lists',
        'lead_lists_leads',
    ];

    /** 需要 unserialize -> json_encode 的列 */
    private const SERIALIZED_COLUMNS = [
        'leads'       => ['internal', 'social_cache'],
        'lead_lists'  => ['filters'],
        'lead_fields' => ['properties'],
        'users'       => ['preferences'],
    ];

    /** 生成列 / 永不写入的列 */
    private const EXCLUDED_COLUMNS = [
        'leads' => ['generated_email_domain'],
    ];

    protected function configure(): void
    {
        $this->setName('etl:mautic')
            ->addOption('truncate', null, Option::VALUE_NONE, '迁移前清空目标表')
            ->addOption('table', 't', Option::VALUE_REQUIRED, '只迁移指定表')
            ->addOption('chunk', 'c', Option::VALUE_REQUIRED, '每批条数（默认 500）', '500')
            ->addOption('dry-run', null, Option::VALUE_NONE, '只统计不写库')
            ->setDescription('把 Mautic 生产库的核心数据迁移到 automarket_tp8');
    }

    protected function execute(Input $input, Output $output): int
    {
        $only     = $input->getOption('table');
        $chunk    = max(50, (int) $input->getOption('chunk'));
        $dryRun   = (bool) $input->getOption('dry-run');
        $truncate = (bool) $input->getOption('truncate');

        $tables = $only ? [$only] : self::TABLES;

        foreach ($tables as $table) {
            if (!in_array($table, self::TABLES, true)) {
                $output->error("未知表：{$table}");

                return 1;
            }
        }

        $output->writeln('<info>=== Mautic -> automarket_tp8 数据迁移 ===</info>');
        $output->writeln($dryRun ? '<comment>模式：DRY-RUN（不写库）</comment>' : '模式：正式写入');

        if ($truncate && !$dryRun) {
            $this->truncateAll(array_reverse($tables), $output);
        }

        $summary = [];

        foreach ($tables as $table) {
            try {
                $summary[$table] = $this->migrateTable($table, $chunk, $dryRun, $output);
            } catch (Throwable $e) {
                $output->error("[{$table}] 迁移失败：" . $e->getMessage());

                return 1;
            }
        }

        if (!$dryRun) {
            $this->resetAutoIncrement($tables, $output);
        }

        $output->writeln('');
        $output->writeln('<info>=== 迁移汇总 ===</info>');
        foreach ($summary as $table => $stat) {
            $output->writeln(sprintf(
                '  %-18s 源 %-6d -> 写入 %-6d  跳过 %d',
                $table,
                $stat['source'],
                $stat['written'],
                $stat['skipped']
            ));
        }

        $output->writeln('<info>完成。</info>');

        return 0;
    }

    /** @return array{source:int,written:int,skipped:int} */
    private function migrateTable(string $table, int $chunk, bool $dryRun, Output $output): array
    {
        $srcColumns = $this->columnsOf('mautic', $table);
        $dstColumns = $this->columnsOf(null, $table);

        if ($srcColumns === []) {
            $output->writeln("  <comment>[{$table}] 源库无此表，跳过</comment>");

            return ['source' => 0, 'written' => 0, 'skipped' => 0];
        }

        $excluded = self::EXCLUDED_COLUMNS[$table] ?? [];
        $columns  = array_values(array_diff(array_intersect($srcColumns, $dstColumns), $excluded));

        if ($columns === []) {
            throw new \RuntimeException('源库与目标库无交集列');
        }

        $missing = array_diff($dstColumns, $srcColumns, $excluded);
        if ($missing !== []) {
            $output->writeln("  <comment>[{$table}] 目标库多出列（将用默认值）：" . implode(', ', $missing) . '</comment>');
        }

        $total   = (int) Db::connect('mautic')->name($table)->count();
        $written = 0;
        $skipped = 0;
        $offset  = 0;

        $serialized = self::SERIALIZED_COLUMNS[$table] ?? [];
        $hasId      = in_array('id', $columns, true);

        while ($offset < $total) {
            $rows = Db::connect('mautic')
                ->name($table)
                ->field($columns)
                ->when($hasId, static fn ($q) => $q->order('id', 'asc'))
                ->limit($offset, $chunk)
                ->select()
                ->toArray();

            if ($rows === []) {
                break;
            }

            $batch = [];
            foreach ($rows as $row) {
                $batch[] = $this->transformRow($row, $serialized);
            }

            if (!$dryRun) {
                // think-orm v4: insertAll(data, limit, replace) — replace=true 保留原ID且可重复执行
                $written += Db::name($table)->insertAll($batch, count($batch), true);
            } else {
                $written += count($batch);
            }

            $offset += $chunk;
        }

        $output->writeln(sprintf('  [%s] %d 行', $table, $written));

        return ['source' => $total, 'written' => $written, 'skipped' => $skipped];
    }

    /** 单行转换：serialize -> JSON，非法日期归 NULL */
    private function transformRow(array $row, array $serializedColumns): array
    {
        foreach ($serializedColumns as $col) {
            if (!array_key_exists($col, $row)) {
                continue;
            }
            $row[$col] = $this->serializedToJson($row[$col]);
        }

        foreach ($row as $key => $value) {
            if (is_string($value) && str_starts_with($value, '0000-00-00')) {
                $row[$key] = null;
            }
        }

        return $row;
    }

    private function serializedToJson(mixed $value): ?string
    {
        if ($value === null || $value === '') {
            return null;
        }

        if (is_array($value)) {
            return json_encode($value, JSON_UNESCAPED_UNICODE);
        }

        $str = (string) $value;

        // 已经是 JSON 就原样保留
        $decoded = json_decode($str, true);
        if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
            return json_encode($decoded, JSON_UNESCAPED_UNICODE);
        }

        $unserialized = @unserialize($str, ['allowed_classes' => false]);
        if ($unserialized === false && $str !== 'b:0;') {
            // 反序列化失败：保留原值，避免静默丢数据
            return $str;
        }

        return json_encode($unserialized === false ? [] : $unserialized, JSON_UNESCAPED_UNICODE);
    }

    private function truncateAll(array $tables, Output $output): void
    {
        Db::execute('SET FOREIGN_KEY_CHECKS = 0');
        foreach ($tables as $table) {
            Db::execute("TRUNCATE TABLE `{$table}`");
        }
        Db::execute('SET FOREIGN_KEY_CHECKS = 1');

        $output->writeln('  <comment>已清空目标表</comment>');
    }

    private function resetAutoIncrement(array $tables, Output $output): void
    {
        foreach ($tables as $table) {
            $cols = $this->columnsOf(null, $table);
            if (!in_array('id', $cols, true)) {
                continue; // 无自增主键的表（如 lead_lists_leads 复合主键）跳过
            }
            $max = Db::name($table)->max('id');
            if ($max) {
                Db::execute("ALTER TABLE `{$table}` AUTO_INCREMENT = " . ((int) $max + 1));
            }
        }

        $output->writeln('  <comment>已重置 AUTO_INCREMENT</comment>');
    }

    /** @return string[] */
    private function columnsOf(?string $connection, string $table): array
    {
        try {
            $query = $connection ? Db::connect($connection) : Db::connect();
            $rows  = $query->query("SHOW COLUMNS FROM `{$table}`");
        } catch (Throwable) {
            return [];
        }

        return array_map(static fn (array $r): string => $r['Field'], $rows);
    }
}
