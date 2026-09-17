-- ============================================================
-- GPA 4.3 scale synchronization
-- Recreates GPA-related routines and recalculates existing grade rows.
-- ============================================================

USE student_management_agent;
SET @previous_safe_updates = @@SQL_SAFE_UPDATES;
SET SQL_SAFE_UPDATES = 0;

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

DROP PROCEDURE IF EXISTS proc_GraduateAudit //

CREATE PROCEDURE proc_GraduateAudit(
    IN  p_student_id VARCHAR(20),
    OUT p_qualified  TINYINT,
    OUT p_message    VARCHAR(500)
)
BEGIN
    DECLARE v_total_credits     DECIMAL(6,1) DEFAULT 0;
    DECLARE v_required_credits  DECIMAL(6,1);
    DECLARE v_cumulative_gpa    DECIMAL(4,2);
    DECLARE v_failed_count      INT DEFAULT 0;
    DECLARE v_status            VARCHAR(20);

    SELECT status, education_length * 16 INTO v_status, v_required_credits
    FROM student WHERE student_id = p_student_id;

    IF v_status IS NULL THEN
        SET p_qualified = 0;
        SET p_message = '学生不存在';
    END IF;

    IF v_status != '在读' THEN
        SET p_qualified = 0;
        SET p_message = CONCAT('学生当前状态为"', v_status, '"，非在读状态');
    END IF;

    SELECT IFNULL(SUM(c.credits), 0) INTO v_total_credits
    FROM enrollment e
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id AND e.status = '已通过';

    SELECT IFNULL(ROUND(SUM(c.credits * g.gpa) / NULLIF(SUM(c.credits), 0), 2), 0)
    INTO v_cumulative_gpa
    FROM enrollment e
    INNER JOIN grade g ON e.enrollment_id = g.enrollment_id
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id AND g.gpa IS NOT NULL;

    SELECT COUNT(*) INTO v_failed_count
    FROM enrollment e
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id
      AND c.course_type = '必修'
      AND e.status = '未通过';

    IF v_total_credits >= v_required_credits AND v_cumulative_gpa >= 2.0 AND v_failed_count = 0 THEN
        SET p_qualified = 1;
        SET p_message = CONCAT('审核通过。已修学分：', v_total_credits,
                               '，累计GPA：', v_cumulative_gpa,
                               '，未通过必修课：0');
    ELSE
        SET p_qualified = 0;
        SET p_message = CONCAT('不满足毕业条件。已修学分：', v_total_credits,
                               '(需', v_required_credits, ')，累计GPA：', v_cumulative_gpa,
                               '(需≥2.0，4.3制)，未通过必修课：', v_failed_count);
    END IF;
END //

DROP TRIGGER IF EXISTS trg_Student_BeforeUpdate //

CREATE TRIGGER trg_Student_BeforeUpdate
BEFORE UPDATE ON student
FOR EACH ROW
BEGIN
    DECLARE v_completed_credits DECIMAL(5,1);
    DECLARE v_gpa DECIMAL(4,2);

    IF NEW.status = '毕业' AND OLD.status != '毕业' THEN
        SET v_completed_credits = fn_GetCompletedCredits(NEW.student_id);
        SET v_gpa = fn_GetStudentGPA(NEW.student_id);

        IF v_completed_credits < NEW.education_length * 16 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '不满足毕业条件：学分未修满';
        END IF;

        IF v_gpa < 2.0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '不满足毕业条件：累计GPA低于2.0（4.3制）';
        END IF;
    END IF;
END //

DELIMITER ;

ALTER TABLE grade
    MODIFY gpa DECIMAL(3,2) COMMENT '绩点(4.3制，0.00-4.30)';

UPDATE grade
SET gpa = fn_ScoreToGPA(total_score)
WHERE total_score IS NOT NULL;
SET SQL_SAFE_UPDATES = @previous_safe_updates;
