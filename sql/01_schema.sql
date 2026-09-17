-- ============================================================
-- 学籍管理系统 (Student Status Management System)
-- 数据库建表脚本 - MySQL 8.0+
-- ============================================================

-- Existing databases are never dropped by this script.
CREATE DATABASE student_management_agent DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE student_management_agent;

-- ============================================================
-- 1. 专业表 (major)
-- ============================================================
CREATE TABLE major (
    major_id    INT AUTO_INCREMENT PRIMARY KEY,
    major_code  VARCHAR(20)  NOT NULL UNIQUE COMMENT '专业代码',
    major_name  VARCHAR(100) NOT NULL COMMENT '专业名称',
    department  VARCHAR(100) NOT NULL COMMENT '所属院系',
    duration    TINYINT      NOT NULL DEFAULT 4 COMMENT '学制(年)',
    degree_type VARCHAR(20)  NOT NULL COMMENT '学位类型(学士/硕士/博士)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='专业信息表';

-- ============================================================
-- 2. 班级表 (class)
-- ============================================================
CREATE TABLE class (
    class_id   INT AUTO_INCREMENT PRIMARY KEY,
    class_name VARCHAR(100) NOT NULL COMMENT '班级名称',
    grade      YEAR         NOT NULL COMMENT '年级',
    counselor  VARCHAR(50)           COMMENT '辅导员姓名',
    major_id   INT          NOT NULL COMMENT '所属专业ID',

    INDEX idx_class_major (major_id),
    CONSTRAINT fk_class_major FOREIGN KEY (major_id) REFERENCES major(major_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班级信息表';

-- ============================================================
-- 3. 学生表 (student)
-- ============================================================
CREATE TABLE student (
    student_id        VARCHAR(20)  PRIMARY KEY  COMMENT '学号',
    name              VARCHAR(50)  NOT NULL     COMMENT '姓名',
    gender            CHAR(1)      NOT NULL     COMMENT '性别(M-男/F-女)',
    birth_date        DATE                      COMMENT '出生日期',
    id_card           VARCHAR(18)  UNIQUE       COMMENT '身份证号',
    ethnicity         VARCHAR(20)               COMMENT '民族',
    political_status  VARCHAR(20)               COMMENT '政治面貌',
    native_place      VARCHAR(100)              COMMENT '籍贯',
    home_address      VARCHAR(200)              COMMENT '家庭住址',
    phone             VARCHAR(20)               COMMENT '联系电话',
    email             VARCHAR(100)              COMMENT '邮箱',
    enrollment_year   YEAR         NOT NULL     COMMENT '入学年份',
    education_length  TINYINT      NOT NULL DEFAULT 4 COMMENT '学制(年)',
    education_level   VARCHAR(20)  NOT NULL     COMMENT '学历层次(本科/专科/硕士/博士)',
    status            VARCHAR(20)  DEFAULT '在读' COMMENT '学籍状态(在读/休学/退学/毕业/肄业)',
    photo             VARCHAR(255)              COMMENT '照片文件路径',
    major_id          INT          NOT NULL     COMMENT '专业ID',
    class_id          INT          NOT NULL     COMMENT '班级ID',
    created_at        DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at        DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    INDEX idx_student_name (name),
    INDEX idx_student_major (major_id),
    INDEX idx_student_class (class_id),
    INDEX idx_student_status (status),
    INDEX idx_student_enrollment_year (enrollment_year),

    CONSTRAINT fk_student_major FOREIGN KEY (major_id) REFERENCES major(major_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_student_class FOREIGN KEY (class_id) REFERENCES class(class_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学生信息表';

-- ============================================================
-- 4. 专业变更记录表 (major_change)
-- ============================================================
CREATE TABLE major_change (
    change_id       INT AUTO_INCREMENT PRIMARY KEY,
    student_id      VARCHAR(20) NOT NULL COMMENT '学号',
    old_major_id    INT         NOT NULL COMMENT '原专业ID',
    new_major_id    INT         NOT NULL COMMENT '新专业ID',
    change_date     DATE        NOT NULL COMMENT '变更日期',
    reason          TEXT                 COMMENT '变更原因',
    approval_status VARCHAR(20) DEFAULT '待审批' COMMENT '审批状态(待审批/已通过/已拒绝)',
    approver_id     INT                  COMMENT '审批人ID(关联user表)',
    approval_date   DATETIME             COMMENT '审批日期',
    attachment      VARCHAR(255)         COMMENT '附件材料路径',

    INDEX idx_mc_student (student_id),
    INDEX idx_mc_status (approval_status),

    CONSTRAINT fk_mc_student   FOREIGN KEY (student_id)   REFERENCES student(student_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_mc_old_major FOREIGN KEY (old_major_id) REFERENCES major(major_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_mc_new_major FOREIGN KEY (new_major_id) REFERENCES major(major_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='专业变更记录表';

-- ============================================================
-- 5. 奖惩记录表 (reward_punishment)
-- ============================================================
CREATE TABLE reward_punishment (
    record_id   INT AUTO_INCREMENT PRIMARY KEY,
    student_id  VARCHAR(20)  NOT NULL COMMENT '学号',
    type        VARCHAR(10)  NOT NULL COMMENT '类型(奖励/惩罚)',
    title       VARCHAR(200) NOT NULL COMMENT '奖惩名称',
    level       VARCHAR(20)           COMMENT '级别(校级/院级/省级/国家级)',
    rp_date     DATE         NOT NULL COMMENT '奖惩日期',
    description TEXT                  COMMENT '描述',
    evidence    VARCHAR(255)          COMMENT '证明材料路径',

    INDEX idx_rp_student (student_id),
    INDEX idx_rp_type (type),
    INDEX idx_rp_date (rp_date),

    CONSTRAINT fk_rp_student FOREIGN KEY (student_id) REFERENCES student(student_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='奖惩记录表';

-- ============================================================
-- 6. 教师表 (teacher)
-- ============================================================
CREATE TABLE teacher (
    teacher_id INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(50)  NOT NULL COMMENT '姓名',
    gender     CHAR(1)               COMMENT '性别(M-男/F-女)',
    title      VARCHAR(50)           COMMENT '职称(教授/副教授/讲师/助教)',
    department VARCHAR(100)          COMMENT '所属院系',
    phone      VARCHAR(20)           COMMENT '联系电话',
    email      VARCHAR(100)          COMMENT '邮箱',

    INDEX idx_teacher_name (name),
    INDEX idx_teacher_dept (department)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='教师信息表';

-- ============================================================
-- 7. 课程表 (course)
-- ============================================================
CREATE TABLE course (
    course_id   INT AUTO_INCREMENT PRIMARY KEY,
    course_code VARCHAR(20)  NOT NULL UNIQUE COMMENT '课程代码',
    course_name VARCHAR(100) NOT NULL COMMENT '课程名称',
    credits     DECIMAL(3,1) NOT NULL COMMENT '学分',
    hours       INT          NOT NULL COMMENT '总学时',
    course_type VARCHAR(20)  NOT NULL COMMENT '课程类型(必修/选修/公选)',
    department  VARCHAR(100)          COMMENT '开课院系',
    description TEXT                  COMMENT '课程描述',
    syllabus    VARCHAR(255)          COMMENT '教学大纲文件路径',

    INDEX idx_course_type (course_type),
    INDEX idx_course_dept (department)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课程信息表';

-- ============================================================
-- 8. 开课信息表 (course_offering)
-- ============================================================
CREATE TABLE course_offering (
    offering_id   INT AUTO_INCREMENT PRIMARY KEY,
    course_id     INT         NOT NULL COMMENT '课程ID',
    teacher_id    INT         NOT NULL COMMENT '授课教师ID',
    academic_year VARCHAR(9)  NOT NULL COMMENT '学年(如2025-2026)',
    semester      VARCHAR(10) NOT NULL COMMENT '学期(第一学期/第二学期)',
    classroom     VARCHAR(100)         COMMENT '上课教室',
    schedule      VARCHAR(200)         COMMENT '上课时间(如 周一1-2节)',
    max_students  INT         NOT NULL DEFAULT 60 COMMENT '最大选课人数',
    cur_students  INT         NOT NULL DEFAULT 0 COMMENT '当前选课人数',

    INDEX idx_co_course (course_id),
    INDEX idx_co_teacher (teacher_id),
    INDEX idx_co_semester (academic_year, semester),

    CONSTRAINT fk_co_course  FOREIGN KEY (course_id)  REFERENCES course(course_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_co_teacher FOREIGN KEY (teacher_id) REFERENCES teacher(teacher_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_cur_students CHECK (cur_students <= max_students)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='开课信息表';

-- ============================================================
-- 9. 选课记录表 (enrollment)
-- ============================================================
CREATE TABLE enrollment (
    enrollment_id  INT AUTO_INCREMENT PRIMARY KEY,
    student_id     VARCHAR(20) NOT NULL COMMENT '学号',
    offering_id    INT         NOT NULL COMMENT '开课ID',
    enroll_date    DATETIME    DEFAULT CURRENT_TIMESTAMP COMMENT '选课日期',
    status         VARCHAR(20) DEFAULT '在修' COMMENT '状态(在修/已通过/未通过/退课)',

    UNIQUE KEY uk_enrollment (student_id, offering_id),
    INDEX idx_enr_offering (offering_id),
    INDEX idx_enr_status (status),

    CONSTRAINT fk_enr_student  FOREIGN KEY (student_id)  REFERENCES student(student_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_enr_offering FOREIGN KEY (offering_id) REFERENCES course_offering(offering_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='选课记录表';

-- ============================================================
-- 10. 成绩表 (grade)
-- ============================================================
CREATE TABLE grade (
    grade_id       INT AUTO_INCREMENT PRIMARY KEY,
    enrollment_id  INT          NOT NULL UNIQUE COMMENT '选课记录ID(一对一)',
    daily_score    DECIMAL(5,2)          COMMENT '平时成绩',
    midterm_score  DECIMAL(5,2)          COMMENT '期中成绩',
    final_score    DECIMAL(5,2)          COMMENT '期末成绩',
    total_score    DECIMAL(5,2)          COMMENT '总评成绩',
    gpa            DECIMAL(3,2)          COMMENT '绩点(4.3制，0.00-4.30)',
    makeup_score   DECIMAL(5,2)          COMMENT '补考成绩',
    status         VARCHAR(20) DEFAULT '正常' COMMENT '成绩状态(正常/补考/重修)',
    recorded_at    DATETIME    DEFAULT CURRENT_TIMESTAMP COMMENT '录入时间',
    updated_at     DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',

    CONSTRAINT fk_grade_enrollment FOREIGN KEY (enrollment_id) REFERENCES enrollment(enrollment_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_scores CHECK (
        daily_score   BETWEEN 0 AND 100 AND
        midterm_score BETWEEN 0 AND 100 AND
        final_score    BETWEEN 0 AND 100 AND
        total_score    BETWEEN 0 AND 100 AND
        makeup_score   BETWEEN 0 AND 100
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='成绩表';

-- ============================================================
-- 11. 系统用户表 (user)
-- ============================================================
CREATE TABLE user (
    user_id    INT AUTO_INCREMENT PRIMARY KEY,
    username   VARCHAR(50)  NOT NULL UNIQUE COMMENT '用户名',
    password   VARCHAR(255) NOT NULL COMMENT '密码(bcrypt加密)',
    role       VARCHAR(20)  NOT NULL COMMENT '角色(admin/teacher/student/counselor)',
    related_id VARCHAR(20)           COMMENT '关联学号，保留前导零和字母',
    last_login DATETIME              COMMENT '最后登录时间',
    is_active  TINYINT(1)   DEFAULT 1 COMMENT '账户状态(0-禁用/1-启用)',

    INDEX idx_user_role (role),
    INDEX idx_user_related (related_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统用户表';

-- ============================================================
-- 12. 文件管理表 (file)
-- ============================================================
CREATE TABLE file (
    file_id       INT AUTO_INCREMENT PRIMARY KEY,
    file_name     VARCHAR(255) NOT NULL COMMENT '原始文件名',
    file_type     VARCHAR(20)  NOT NULL COMMENT '类型(image/video/document)',
    file_path     VARCHAR(500) NOT NULL COMMENT '服务器存储路径',
    related_table VARCHAR(50)  NOT NULL COMMENT '关联表名',
    related_id    VARCHAR(50)  NOT NULL COMMENT '关联记录ID',
    upload_time   DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    file_size     BIGINT                COMMENT '文件大小(字节)',

    INDEX idx_file_related (related_table, related_id),
    INDEX idx_file_type (file_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件管理表';

-- ============================================================
-- 13. 操作日志表 (audit_log)
-- ============================================================
CREATE TABLE audit_log (
    log_id      INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT          NOT NULL COMMENT '操作用户ID',
    action      VARCHAR(50)  NOT NULL COMMENT '操作类型(INSERT/UPDATE/DELETE)',
    table_name  VARCHAR(50)  NOT NULL COMMENT '操作表名',
    record_id   VARCHAR(50)           COMMENT '操作记录ID',
    old_value   JSON                  COMMENT '修改前值',
    new_value   JSON                  COMMENT '修改后值',
    ip_address  VARCHAR(50)           COMMENT '客户端IP',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',

    INDEX idx_log_user (user_id),
    INDEX idx_log_time (created_at),
    INDEX idx_log_table (table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作日志表';
