-- ============================================================
-- TutorMatch A.I. — MySQL schema for the secure auth backend
-- MySQL 8.0+
--
-- Run once:
--   mysql -u root -p < schema.sql
--
-- All timestamps are stored in UTC. db.py sets the connection
-- time zone to +00:00 so DATETIME values are consistent.
-- ============================================================

CREATE DATABASE IF NOT EXISTS tutormatch
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE tutormatch;

-- ------------------------------------------------------------
-- 1. users
-- One row per account. This is the only table that stores
-- password hashes. Never store a plain password anywhere.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  role               ENUM('student', 'tutor', 'admin') NOT NULL DEFAULT 'student',
  name               VARCHAR(80)  NOT NULL,
  email              VARCHAR(254) NOT NULL,
  password_hash      VARCHAR(255) NOT NULL,

  -- NULL means the email has not been verified yet.
  email_verified_at  DATETIME NULL,

  -- Lockout state. failed_attempts is reset after a good login.
  failed_attempts    INT UNSIGNED NOT NULL DEFAULT 0,
  locked_until       DATETIME NULL,

  -- Increment this after a password change/reset. Any session
  -- holding an older number is rejected by the app.
  session_version    INT UNSIGNED NOT NULL DEFAULT 0,

  -- Useful for the "new login" alert and the admin dashboard.
  last_login_at      DATETIME NULL,
  last_login_ip      VARCHAR(45) NULL,
  password_changed_at DATETIME NULL,

  status             ENUM('active', 'suspended') NOT NULL DEFAULT 'active',
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                       ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email),
  KEY idx_users_role (role),
  KEY idx_users_locked (locked_until)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. email_otps
-- One row per OTP sent. The 6-digit code is never stored in
-- plain text: otp_hash is an HMAC-SHA256 of the code using a
-- secret pepper from .env.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_otps (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     BIGINT UNSIGNED NOT NULL,
  otp_hash    CHAR(64) NOT NULL,          -- hex HMAC-SHA256
  expires_at  DATETIME NOT NULL,
  attempts    INT UNSIGNED NOT NULL DEFAULT 0,
  used_at     DATETIME NULL,              -- set when accepted or burned
  ip_address  VARCHAR(45) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_otp_user (user_id, created_at),
  KEY idx_otp_expiry (expires_at),
  CONSTRAINT fk_otp_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3. password_resets
-- One row per reset link. token_hash is SHA-256 of the random
-- token that was emailed. The raw token is never stored.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_resets (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     BIGINT UNSIGNED NOT NULL,
  token_hash  CHAR(64) NOT NULL,          -- hex SHA-256
  expires_at  DATETIME NOT NULL,
  used_at     DATETIME NULL,
  ip_address  VARCHAR(45) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_reset_token (token_hash),
  KEY idx_reset_user (user_id, created_at),
  KEY idx_reset_expiry (expires_at),
  CONSTRAINT fk_reset_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 4. security_events
-- Append-only security log. It is the source for:
--   - the admin dashboard
--   - monitor.py suspicious-activity scan
--   - per-IP rate limiting (count recent rows by event_type)
--
-- email_tried is private admin data. It is never returned to
-- the browser and never used to tell a user whether an account
-- exists.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS security_events (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_type  VARCHAR(40) NOT NULL,
  user_id     BIGINT UNSIGNED NULL,
  email_tried VARCHAR(254) NULL,
  ip_address  VARCHAR(45) NOT NULL,
  user_agent  VARCHAR(255) NULL,
  details     VARCHAR(255) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  KEY idx_events_type_time (event_type, created_at),
  KEY idx_events_ip_time (ip_address, created_at),
  KEY idx_events_user_time (user_id, created_at),
  KEY idx_events_time (created_at),
  CONSTRAINT fk_event_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 5. profiles
-- One row per user. Profile-specific fields only; users.name,
-- users.email and users.role stay in the users table.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profiles (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id               BIGINT UNSIGNED NOT NULL,
  photo_url             VARCHAR(255) NULL,
  bio                   VARCHAR(600) NULL,
  birthdate             DATE NULL,
  headline              VARCHAR(120) NULL,
  status                ENUM('active', 'away', 'accepting', 'not_accepting')
                          NOT NULL DEFAULT 'active',
  format                ENUM('online', 'in_person', 'both') NULL,
  area_barangay         VARCHAR(80) NULL,
  area_city             VARCHAR(80) NOT NULL DEFAULT 'Cabadbaran City',
  coarse_geohash        VARCHAR(12) NULL,
  rate_centavos         INT UNSIGNED NULL,
  budget_min_centavos   INT UNSIGNED NULL,
  budget_max_centavos   INT UNSIGNED NULL,
  currency              CHAR(3) NOT NULL DEFAULT 'PHP',
  style_tags            JSON NULL,
  goal_tags             JSON NULL,
  completeness          TINYINT UNSIGNED NOT NULL DEFAULT 0,
  onboarding_step       TINYINT UNSIGNED NOT NULL DEFAULT 1,
  onboarding_completed_at DATETIME NULL,
  verified_at           DATETIME NULL,
  response_time_mins    INT UNSIGNED NULL,
  last_active_at        DATETIME NULL,
  created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                          ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  UNIQUE KEY uq_profiles_user (user_id),
  KEY idx_profiles_search (completeness, onboarding_completed_at),
  CONSTRAINT fk_profiles_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 6. subjects
-- Reference list used by onboarding and search.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subjects (
  id       VARCHAR(40) NOT NULL,
  name     VARCHAR(80) NOT NULL,
  category VARCHAR(80) NOT NULL,

  PRIMARY KEY (id),
  KEY idx_subjects_category (category)
) ENGINE=InnoDB;

INSERT IGNORE INTO subjects (id, name, category) VALUES
  ('sub_mathematics', 'Mathematics', 'Mathematics'),
  ('sub_algebra', 'Algebra', 'Mathematics'),
  ('sub_calculus', 'Calculus', 'Mathematics'),
  ('sub_geometry', 'Geometry', 'Mathematics'),
  ('sub_statistics', 'Statistics', 'Mathematics'),
  ('sub_physics', 'Physics', 'Science'),
  ('sub_chemistry', 'Chemistry', 'Science'),
  ('sub_biology', 'Biology', 'Science'),
  ('sub_english', 'English', 'Languages'),
  ('sub_filipino', 'Filipino', 'Languages'),
  ('sub_ielts', 'IELTS', 'Languages'),
  ('sub_programming', 'Programming', 'Technology'),
  ('sub_python', 'Python', 'Technology'),
  ('sub_web', 'Web Development', 'Technology'),
  ('sub_accounting', 'Accounting', 'Business'),
  ('sub_economics', 'Economics', 'Business');

-- ------------------------------------------------------------
-- 7. profile_subjects
-- What a tutor teaches or a student needs, with a level.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profile_subjects (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  profile_id BIGINT UNSIGNED NOT NULL,
  subject_id VARCHAR(40) NOT NULL,
  level      ENUM('elementary', 'high_school', 'senior_high', 'college', 'adult')
               NOT NULL,
  kind       ENUM('teach', 'need') NOT NULL,

  PRIMARY KEY (id),
  UNIQUE KEY uq_profile_subject (profile_id, subject_id, kind, level),
  KEY idx_profile_subjects_profile (profile_id),
  CONSTRAINT fk_ps_profile
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_ps_subject
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 8. availability_slots
-- Weekly availability. 1 = Monday, 7 = Sunday.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS availability_slots (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  profile_id  BIGINT UNSIGNED NOT NULL,
  day_of_week TINYINT UNSIGNED NOT NULL,
  start_time  TIME NOT NULL,
  end_time    TIME NOT NULL,
  timezone    VARCHAR(40) NOT NULL DEFAULT 'Asia/Manila',

  PRIMARY KEY (id),
  UNIQUE KEY uq_availability (profile_id, day_of_week, start_time, end_time),
  KEY idx_availability_profile (profile_id),
  CONSTRAINT fk_availability_profile
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT chk_availability_day
    CHECK (day_of_week BETWEEN 1 AND 7),
  CONSTRAINT chk_availability_time
    CHECK (start_time < end_time)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- Optional reset for local development only.
-- Uncomment these lines if you want a clean database.
-- ------------------------------------------------------------
-- SET FOREIGN_KEY_CHECKS = 0;
-- DROP TABLE IF EXISTS security_events;
-- DROP TABLE IF EXISTS password_resets;
-- DROP TABLE IF EXISTS email_otps;
-- DROP TABLE IF EXISTS users;
-- SET FOREIGN_KEY_CHECKS = 1;
