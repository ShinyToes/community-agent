-- ============================================================
-- 学籍管理系统 - 函数 (Functions)
-- ============================================================

USE student_management_agent;

-- ============================================================
-- FN1: fn_GetStudentGPA — 获取学生累计GPA
-- 输入: student_id
-- 输出: DECIMAL(4,2) 累计加权平均绩点
-- 算法: SUM(学分 × 绩点) / SUM(学分)
-- ============================================================
DELIMITER //

DROP FUNCTION IF EXISTS fn_GetStudentGPA //

CREATE FUNCTION fn_GetStudentGPA(p_student_id VARCHAR(20))
RETURNS DECIMAL(4,2)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_gpa DECIMAL(4,2);

    SELECT ROUND(SUM(c.credits * g.gpa) / NULLIF(SUM(c.credits), 0), 2)
    INTO v_gpa
    FROM enrollment e
    INNER JOIN grade g ON e.enrollment_id = g.enrollment_id
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id
      AND g.gpa IS NOT NULL
      AND e.status IN ('已通过', '在修');

    RETURN IFNULL(v_gpa, 0.00);
END //

DELIMITER ;


-- ============================================================
-- FN2: fn_GetCompletedCredits — 获取已修学分
-- 输入: student_id
-- 输出: DECIMAL(5,1) 已修完的总学分
-- ============================================================
DELIMITER //

DROP FUNCTION IF EXISTS fn_GetCompletedCredits //

CREATE FUNCTION fn_GetCompletedCredits(p_student_id VARCHAR(20))
RETURNS DECIMAL(5,1)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_credits DECIMAL(5,1);

    SELECT IFNULL(SUM(c.credits), 0)
    INTO v_credits
    FROM enrollment e
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id
      AND e.status = '已通过';

    RETURN v_credits;
END //

DELIMITER ;


-- ============================================================
-- FN3: fn_CheckCourseConflict — 检查课程时间冲突
-- 输入: student_id, offering_id
-- 输出: TINYINT(1) — 0=不冲突, 1=冲突
-- ============================================================
DELIMITER //

DROP FUNCTION IF EXISTS fn_CheckCourseConflict //

CREATE FUNCTION fn_CheckCourseConflict(
    p_student_id VARCHAR(20),
    p_offering_id INT
)
RETURNS TINYINT
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_conflict_count INT DEFAULT 0;
    DECLARE v_target_schedule VARCHAR(200);

    -- 获取目标课程的时间安排
    SELECT schedule INTO v_target_schedule
    FROM course_offering
    WHERE offering_id = p_offering_id;

    -- 如果目标课程或已有课程没有安排时间，视为不冲突
    IF v_target_schedule IS NULL OR v_target_schedule = '' THEN
        RETURN 0;
    END IF;

    -- 查找学生已选课程中是否有时间重叠
    SELECT COUNT(*) INTO v_conflict_count
    FROM enrollment e
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course_offering target ON target.offering_id = p_offering_id
    WHERE e.student_id = p_student_id
      AND e.status IN ('在修')
      AND co.academic_year = target.academic_year
      AND co.semester = target.semester
      AND co.schedule = v_target_schedule
      AND co.offering_id != p_offering_id;

    RETURN IF(v_conflict_count > 0, 1, 0);
END //

DELIMITER ;


-- ============================================================
-- FN4: fn_GetClassRanking — 获取学生班级排名
-- 输入: student_id, academic_year, semester
-- 输出: INT 班级排名
-- ============================================================
DELIMITER //

DROP FUNCTION IF EXISTS fn_GetClassRanking //

CREATE FUNCTION fn_GetClassRanking(
    p_student_id    VARCHAR(20),
    p_academic_year VARCHAR(9),
    p_semester      VARCHAR(10)
)
RETURNS INT
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_class_id INT;
    DECLARE v_ranking  INT DEFAULT 0;

    -- 获取学生所在班级
    SELECT class_id INTO v_class_id
    FROM student WHERE student_id = p_student_id;

    IF v_class_id IS NULL THEN
        RETURN -1;
    END IF;

    -- 计算在班级内的排名(按平均成绩降序)
    SELECT COUNT(*) + 1 INTO v_ranking
    FROM (
        SELECT e.student_id
        FROM enrollment e
        INNER JOIN grade g ON e.enrollment_id = g.enrollment_id
        INNER JOIN course_offering co ON e.offering_id = co.offering_id
        INNER JOIN student s ON e.student_id = s.student_id
        WHERE s.class_id = v_class_id
          AND co.academic_year = p_academic_year
          AND co.semester = p_semester
          AND g.total_score IS NOT NULL
          AND e.status IN ('已通过', '在修')
        GROUP BY e.student_id
        HAVING AVG(g.total_score) > (
            SELECT AVG(g2.total_score)
            FROM enrollment e2
            INNER JOIN grade g2 ON e2.enrollment_id = g2.enrollment_id
            INNER JOIN course_offering co2 ON e2.offering_id = co2.offering_id
            WHERE e2.student_id = p_student_id
              AND co2.academic_year = p_academic_year
              AND co2.semester = p_semester
              AND g2.total_score IS NOT NULL
        )
    ) AS higher_ranked;

    RETURN v_ranking;
END //

DELIMITER ;


-- ============================================================
-- FN5: fn_ScoreToGPA — 百分制成绩转换为绩点
-- 输入: 百分制成绩
-- 输出: 绩点 (4.3制)
-- ============================================================
DELIMITER //

DROP FUNCTION IF EXISTS fn_ScoreToGPA //

CREATE FUNCTION fn_ScoreToGPA(p_score DECIMAL(5,2))
RETURNS DECIMAL(3,1)
DETERMINISTIC
NO SQL
BEGIN
    DECLARE v_gpa DECIMAL(3,1);

    CASE
        WHEN p_score >= 95 THEN SET v_gpa = 4.3;
        WHEN p_score >= 90 THEN SET v_gpa = 4.0;
        WHEN p_score >= 85 THEN SET v_gpa = 3.7;
        WHEN p_score >= 82 THEN SET v_gpa = 3.3;
        WHEN p_score >= 78 THEN SET v_gpa = 3.0;
        WHEN p_score >= 75 THEN SET v_gpa = 2.7;
        WHEN p_score >= 72 THEN SET v_gpa = 2.3;
        WHEN p_score >= 68 THEN SET v_gpa = 2.0;
        WHEN p_score >= 65 THEN SET v_gpa = 1.7;
        WHEN p_score >= 64 THEN SET v_gpa = 1.5;
        WHEN p_score >= 61 THEN SET v_gpa = 1.3;
        WHEN p_score >= 60 THEN SET v_gpa = 1.0;
        ELSE SET v_gpa = 0.0;
    END CASE;

    RETURN v_gpa;
END //

DELIMITER ;
