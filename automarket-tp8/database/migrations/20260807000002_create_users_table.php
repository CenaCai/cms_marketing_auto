<?php

declare(strict_types=1);

use think\migration\Migrator;

/**
 * users —— 1:1 复刻 Mautic `users` 表。
 *
 * 说明：Mautic 源库 users.role_id 有外键指向 roles 表，但本阶段只迁移 9 张核心表，
 * 不含 roles，故此处保留 role_id 列（plain int，非空，源数据均为 1）但不建外键约束。
 */
class CreateUsersTable extends Migrator
{
    public function up(): void
    {
        $this->execute(<<<'SQL'
CREATE TABLE IF NOT EXISTS `users` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `role_id` int(10) unsigned NOT NULL,
  `is_published` tinyint(1) NOT NULL,
  `date_added` datetime DEFAULT NULL,
  `created_by` int(11) DEFAULT NULL,
  `created_by_user` varchar(191) DEFAULT NULL,
  `date_modified` datetime DEFAULT NULL,
  `modified_by` int(11) DEFAULT NULL,
  `modified_by_user` varchar(191) DEFAULT NULL,
  `checked_out` datetime DEFAULT NULL,
  `checked_out_by` int(11) DEFAULT NULL,
  `checked_out_by_user` varchar(191) DEFAULT NULL,
  `username` varchar(191) NOT NULL,
  `password` varchar(64) NOT NULL,
  `first_name` varchar(191) NOT NULL,
  `last_name` varchar(191) NOT NULL,
  `email` varchar(191) NOT NULL,
  `position` varchar(191) DEFAULT NULL,
  `timezone` varchar(191) DEFAULT NULL,
  `locale` varchar(191) DEFAULT NULL,
  `last_login` datetime DEFAULT NULL,
  `last_active` datetime DEFAULT NULL,
  `preferences` longtext DEFAULT NULL,
  `signature` longtext DEFAULT NULL,
  `uuid` char(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `UNIQ_username` (`username`),
  UNIQUE KEY `UNIQ_email` (`email`),
  KEY `IDX_role_id` (`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC;
SQL);
    }

    public function down(): void
    {
        $this->execute('DROP TABLE IF EXISTS `users`');
    }
}
