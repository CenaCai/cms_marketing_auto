<?php

declare(strict_types=1);

namespace app\command;

use app\model\LeadList;
use app\service\SegmentService;
use think\console\Command;
use think\console\Input;
use think\console\input\Option;
use think\console\Output;
use Throwable;

/**
 * 重建分群成员，对应 Mautic 的 `mautic:segments:update`。
 *
 * 用法：
 *   php think segments:update                 重建全部已发布分群
 *   php think segments:update --id=9           只重建 9 号分群
 *   php think segments:update --dry-run        只统计命中数
 */
class SegmentsUpdate extends Command
{
    protected function configure(): void
    {
        $this->setName('segments:update')
            ->addOption('id', 'i', Option::VALUE_REQUIRED, '只重建指定分群 ID')
            ->addOption('dry-run', null, Option::VALUE_NONE, '只统计命中数，不落库')
            ->setDescription('重建分群成员（对应 mautic:segments:update）');
    }

    protected function execute(Input $input, Output $output): int
    {
        /** @var SegmentService $service */
        $service = app(SegmentService::class);

        $onlyId = $input->getOption('id');
        $dryRun = (bool) $input->getOption('dry-run');

        $query = LeadList::whereNull('deleted')->where('is_published', 1);
        if ($onlyId) {
            $query->where('id', (int) $onlyId);
        }

        $segments = $query->order('id', 'asc')->select();

        if (count($segments) === 0) {
            $output->writeln('<comment>没有需要重建的分群</comment>');

            return 0;
        }

        $failed = 0;

        foreach ($segments as $segment) {
            $id   = (int) $segment->id;
            $name = (string) $segment->name;

            try {
                if ($dryRun) {
                    $r = $service->preview($id);
                    $output->writeln(sprintf('  #%-3d %-24s 命中 %-6d 当前 %d', $id, $name, $r['matched'], $r['current']));
                } else {
                    $r = $service->rebuild($id);
                    $output->writeln(sprintf(
                        '  #%-3d %-24s 命中 %-6d +%-5d -%-5d 总计 %d',
                        $id, $name, $r['matched'], $r['added'], $r['removed'], $r['total']
                    ));
                }
            } catch (Throwable $e) {
                ++$failed;
                $output->error(sprintf('  #%-3d %-24s 失败：%s', $id, $name, $e->getMessage()));
            }
        }

        if ($failed > 0) {
            $output->writeln("<comment>{$failed} 个分群重建失败（多为过滤器引用了不存在的字段）</comment>");
        }

        return $failed > 0 ? 1 : 0;
    }
}
