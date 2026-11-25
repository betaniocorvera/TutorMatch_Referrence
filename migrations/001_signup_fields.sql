-- ============================================================
-- Migration: full sign-up fields
--
-- schema.sql already contains these columns for a fresh database.
-- Run this file only when upgrading an existing TutorMatch
-- database that was created before the full sign-up flow.
--
--   mysql -u root -p tutormatch < migrations/001_signup_fields.sql
-- ============================================================

USE tutormatch;

ALTER TABLE users
  ADD COLUMN first_name  VARCHAR(50) NULL AFTER name,
  ADD COLUMN middle_name VARCHAR(50) NULL AFTER first_name,
  ADD COLUMN last_name   VARCHAR(50) NULL AFTER middle_name;

ALTER TABLE profiles
  ADD COLUMN gender ENUM('male', 'female', 'other', 'prefer_not_to_say')
    NULL AFTER birthdate,
  ADD COLUMN phone VARCHAR(20) NULL AFTER gender,
  ADD COLUMN address_line VARCHAR(160) NULL AFTER phone,
  ADD COLUMN province VARCHAR(80) NULL AFTER address_line,
  ADD COLUMN postal_code VARCHAR(10) NULL AFTER province,
  ADD COLUMN school VARCHAR(120) NULL AFTER postal_code,
  ADD COLUMN grade_level VARCHAR(40) NULL AFTER school,
  ADD COLUMN course VARCHAR(120) NULL AFTER grade_level,
  ADD COLUMN education VARCHAR(80) NULL AFTER course,
  ADD COLUMN experience_years TINYINT UNSIGNED NULL AFTER education,
  ADD COLUMN show_phone TINYINT(1) NOT NULL DEFAULT 0 AFTER experience_years,
  ADD COLUMN show_address TINYINT(1) NOT NULL DEFAULT 0 AFTER show_phone;
