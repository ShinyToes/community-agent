-- ============================================================
-- 学籍管理系统 - Schema 3NF 更新（可重复执行版）
-- 新增 college 表 + 重构 major/teacher 外键
-- ============================================================

USE student_management_agent;
SET SQL_SAFE_UPDATES = 0;

-- 1. 创建学院表（如果不存在）
CREATE TABLE IF NOT EXISTS college (
    college_id   INT AUTO_INCREMENT PRIMARY KEY,
    college_code VARCHAR(20)  NOT NULL UNIQUE COMMENT '学院代码',
    college_name VARCHAR(100) NOT NULL COMMENT '学院名称',
    dean         VARCHAR(50)           COMMENT '院长姓名',
    office       VARCHAR(100)          COMMENT '办公地点',
    phone        VARCHAR(20)           COMMENT '办公电话'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学院信息表';

-- 2. 插入学院数据（仅在 college 表为空时）
INSERT IGNORE INTO college (college_code, college_name) VALUES
('CS',   '计算机学院'),
('EE',   '电子工程学院'),
('MATH', '理学院'),
('MGMT', '管理学院');

-- 3. 给 major 表添加 college_id 列（仅当不存在时）
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='major' AND COLUMN_NAME='college_id');
SET @sql_add_col = IF(@col_exists = 0,
    'ALTER TABLE major ADD COLUMN college_id INT AFTER degree_type',
    'SELECT ''college_id already exists in major'' AS msg');
PREPARE stmt FROM @sql_add_col; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4. 根据 department 字段更新 college_id（跳过已更新的行）
UPDATE major SET college_id = (SELECT college_id FROM college WHERE college_name = major.department)
WHERE college_id IS NULL;

-- 5. 设置 college_id 为 NOT NULL（如果还不是）
ALTER TABLE major MODIFY college_id INT NOT NULL;
-- 添加外键（如果不存在）
SET @fk_exists = (SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='major' AND CONSTRAINT_NAME='fk_major_college');
SET @sql_add_fk = IF(@fk_exists = 0,
    'ALTER TABLE major ADD CONSTRAINT fk_major_college FOREIGN KEY (college_id) REFERENCES college(college_id) ON DELETE RESTRICT ON UPDATE CASCADE',
    'SELECT ''fk_major_college already exists'' AS msg');
PREPARE stmt FROM @sql_add_fk; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 6. 删除旧的 department 列（仅当存在时）
SET @dept_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='major' AND COLUMN_NAME='department');
SET @sql_drop_dept = IF(@dept_exists > 0,
    'ALTER TABLE major DROP COLUMN department',
    'SELECT ''department already dropped'' AS msg');
PREPARE stmt FROM @sql_drop_dept; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 7. 给 teacher 表添加 college_id（仅当不存在时）
SET @tc_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='teacher' AND COLUMN_NAME='college_id');
SET @sql_tc = IF(@tc_exists = 0,
    'ALTER TABLE teacher ADD COLUMN college_id INT AFTER department',
    'SELECT ''college_id already exists in teacher'' AS msg');
PREPARE stmt FROM @sql_tc; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 更新 teacher.college_id
UPDATE teacher SET college_id = (SELECT college_id FROM college WHERE college_name = teacher.department)
WHERE college_id IS NULL;

-- 添加 teacher 外键（如果不存在）
SET @tfk_exists = (SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='teacher' AND CONSTRAINT_NAME='fk_teacher_college');
SET @sql_tfk = IF(@tfk_exists = 0,
    'ALTER TABLE teacher ADD CONSTRAINT fk_teacher_college FOREIGN KEY (college_id) REFERENCES college(college_id) ON DELETE SET NULL ON UPDATE CASCADE',
    'SELECT ''fk_teacher_college already exists'' AS msg');
PREPARE stmt FROM @sql_tfk; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 8. 给 course 表添加 college_id（仅当不存在时）
SET @cc_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='course' AND COLUMN_NAME='college_id');
SET @sql_cc = IF(@cc_exists = 0,
    'ALTER TABLE course ADD COLUMN college_id INT AFTER department',
    'SELECT ''college_id already exists in course'' AS msg');
PREPARE stmt FROM @sql_cc; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 更新 course.college_id
UPDATE course SET college_id = (SELECT college_id FROM college WHERE college_name = course.department)
WHERE college_id IS NULL;

-- 添加 course 外键（如果不存在）
SET @cfk_exists = (SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA='student_management_agent' AND TABLE_NAME='course' AND CONSTRAINT_NAME='fk_course_college');
SET @sql_cfk = IF(@cfk_exists = 0,
    'ALTER TABLE course ADD CONSTRAINT fk_course_college FOREIGN KEY (college_id) REFERENCES college(college_id) ON DELETE SET NULL ON UPDATE CASCADE',
    'SELECT ''fk_course_college already exists'' AS msg');
PREPARE stmt FROM @sql_cfk; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET SQL_SAFE_UPDATES = 1;
-- 脚本结束
