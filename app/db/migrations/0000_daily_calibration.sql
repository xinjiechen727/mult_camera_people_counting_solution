CREATE TABLE IF NOT EXISTS `daily_calibrations` (
  `id` bigint unsigned AUTO_INCREMENT NOT NULL,
  `date` date NOT NULL,
  `daily_target` int NOT NULL,
  `daily_cap` int NOT NULL,
  `calibration_ratio` double NOT NULL,
  `history_days_used` int NOT NULL,
  `history_raw_average` double NOT NULL,
  `history_raw_median` double NOT NULL,
  `raw_count` int NOT NULL DEFAULT 0,
  `adjusted_count` int NOT NULL DEFAULT 0,
  `region_allocations` json NOT NULL,
  `finalized_at` timestamp NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT `daily_calibrations_date_unique` UNIQUE (`date`),
  CONSTRAINT `daily_calibrations_id` PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `visitor_baselines` (
  `id` bigint unsigned AUTO_INCREMENT NOT NULL,
  `total_baseline` int NOT NULL,
  `year_baseline` int NOT NULL,
  `month_baseline` int NOT NULL,
  `week_baseline` int NOT NULL,
  `baseline_as_of` timestamp NOT NULL,
  `baseline_day` date NOT NULL,
  `baseline_day_adjusted_count` int NOT NULL,
  `year_start` date NOT NULL,
  `month_start` date NOT NULL,
  `week_start` date NOT NULL,
  `timezone` varchar(64) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT `visitor_baselines_id` PRIMARY KEY (`id`)
);
