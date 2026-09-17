-- ============================================================
-- 学籍管理系统 - 体检记录表
-- ============================================================

USE student_management_agent;

CREATE TABLE IF NOT EXISTS physical_exam (
    exam_id       INT AUTO_INCREMENT PRIMARY KEY,
    student_id    VARCHAR(20)  NOT NULL COMMENT '学号',
    exam_date     DATE         NOT NULL COMMENT '体检日期',
    height        DECIMAL(5,1)          COMMENT '身高(cm)',
    weight        DECIMAL(5,1)          COMMENT '体重(kg)',
    vision_left   DECIMAL(4,1)          COMMENT '左眼视力',
    vision_right  DECIMAL(4,1)          COMMENT '右眼视力',
    blood_type    VARCHAR(5)            COMMENT '血型',
    health_status VARCHAR(50)           COMMENT '健康状况',
    hospital      VARCHAR(100)          COMMENT '体检医院',
    report_file   VARCHAR(255)          COMMENT '体检报告文件路径',
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',

    INDEX idx_pe_student (student_id),
    INDEX idx_pe_date (exam_date),

    CONSTRAINT fk_pe_student FOREIGN KEY (student_id) REFERENCES student(student_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='体检记录表';
