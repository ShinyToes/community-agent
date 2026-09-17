-- ============================================================
-- 学籍管理系统 - 课程自定义权重
-- 每门开课可独立设置总评成绩计算权重
-- ============================================================

USE student_management_agent;

ALTER TABLE course_offering
    ADD COLUMN daily_weight   DECIMAL(3,2) NOT NULL DEFAULT 0.30 COMMENT '平时成绩权重',
    ADD COLUMN midterm_weight DECIMAL(3,2) NOT NULL DEFAULT 0.30 COMMENT '期中成绩权重',
    ADD COLUMN final_weight   DECIMAL(3,2) NOT NULL DEFAULT 0.40 COMMENT '期末成绩权重';
