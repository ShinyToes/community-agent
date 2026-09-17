-- ============================================================
-- 学籍管理系统 - 触发器 (Triggers)
-- ============================================================

USE student_management_agent;

-- ============================================================
-- TRG1: trg_Enrollment_AfterInsert
-- 时机: AFTER INSERT ON enrollment
-- 功能: 选课成功后，自动更新开课表的当前选课人数 +1
-- 注意: 此触发器作为 proc_EnrollStudent 的补充保护
-- ============================================================
DELIMITER //

DROP TRIGGER IF EXISTS trg_Enrollment_AfterInsert //

CREATE TRIGGER trg_Enrollment_AfterInsert
AFTER INSERT ON enrollment
FOR EACH ROW
BEGIN
    UPDATE course_offering
    SET cur_students = cur_students + 1
    WHERE offering_id = NEW.offering_id;
END //

DELIMITER ;


-- ============================================================
-- TRG2: trg_Enrollment_AfterDelete
-- 时机: AFTER DELETE ON enrollment
-- 功能: 退课后，自动更新开课表的当前选课人数 -1(最少为0)
-- ============================================================
DELIMITER //

DROP TRIGGER IF EXISTS trg_Enrollment_AfterDelete //

CREATE TRIGGER trg_Enrollment_AfterDelete
AFTER DELETE ON enrollment
FOR EACH ROW
BEGIN
    IF OLD.status != '退课' THEN
        UPDATE course_offering
        SET cur_students = GREATEST(cur_students - 1, 0)
        WHERE offering_id = OLD.offering_id;
    END IF;
END //

DELIMITER ;


-- ============================================================
-- TRG3: trg_Grade_AfterUpdate — 成绩修改审计
-- 时机: AFTER UPDATE ON grade
-- 功能: 成绩被修改时，自动记录修改前/后的值到审计日志表
-- ============================================================
DELIMITER //

DROP TRIGGER IF EXISTS trg_Grade_AfterUpdate //

CREATE TRIGGER trg_Grade_AfterUpdate
AFTER UPDATE ON grade
FOR EACH ROW
BEGIN
    -- 只有成绩字段发生实际变化时才记录
    IF NOT (OLD.daily_score   <=> NEW.daily_score   AND
            OLD.midterm_score <=> NEW.midterm_score AND
            OLD.final_score   <=> NEW.final_score   AND
            OLD.total_score   <=> NEW.total_score   AND
            OLD.gpa           <=> NEW.gpa           AND
            OLD.makeup_score  <=> NEW.makeup_score AND
            OLD.status        <=> NEW.status)
    THEN
        INSERT INTO audit_log (
            user_id, action, table_name, record_id,
            old_value, new_value, created_at
        ) VALUES (
            IFNULL(@current_user_id, 0),
            'UPDATE',
            'grade',
            NEW.grade_id,
            JSON_OBJECT(
                'daily_score',   OLD.daily_score,
                'midterm_score', OLD.midterm_score,
                'final_score',   OLD.final_score,
                'total_score',   OLD.total_score,
                'gpa',           OLD.gpa,
                'makeup_score',  OLD.makeup_score,
                'status',        OLD.status
            ),
            JSON_OBJECT(
                'daily_score',   NEW.daily_score,
                'midterm_score', NEW.midterm_score,
                'final_score',   NEW.final_score,
                'total_score',   NEW.total_score,
                'gpa',           NEW.gpa,
                'makeup_score',  NEW.makeup_score,
                'status',        NEW.status
            ),
            NOW()
        );
    END IF;
END //

DELIMITER ;


-- ============================================================
-- TRG4: trg_Student_BeforeDelete — 防止删除有选课记录的学生
-- 时机: BEFORE DELETE ON student
-- 功能: 阻止删除还有在修选课记录的学生，保护数据完整性
-- ============================================================
DELIMITER //

DROP TRIGGER IF EXISTS trg_Student_BeforeDelete //

CREATE TRIGGER trg_Student_BeforeDelete
BEFORE DELETE ON student
FOR EACH ROW
BEGIN
    DECLARE v_enrollment_count INT DEFAULT 0;

    SELECT COUNT(*) INTO v_enrollment_count
    FROM enrollment
    WHERE student_id = OLD.student_id
      AND status = '在修';

    IF v_enrollment_count > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = '不能删除该学生：存在在修课程记录，请先完成退课处理';
    END IF;
END //

DELIMITER ;


-- ============================================================
-- TRG5: trg_Grade_BeforeInsert — 成绩录入时自动计算绩点
-- 时机: BEFORE INSERT ON grade
-- 功能: 如果提供了total_score但未提供gpa，自动调用fn_ScoreToGPA计算
-- ============================================================
DELIMITER //

DROP TRIGGER IF EXISTS trg_Grade_BeforeInsert //

CREATE TRIGGER trg_Grade_BeforeInsert
BEFORE INSERT ON grade
FOR EACH ROW
BEGIN
    -- 总评分由应用层校验权重并计算，缺少必需分项时保持 NULL。

    -- 自动计算绩点
    IF NEW.gpa IS NULL AND NEW.total_score IS NOT NULL THEN
        SET NEW.gpa = fn_ScoreToGPA(NEW.total_score);
    END IF;

    -- 根据成绩判断状态
    IF NEW.status IS NULL AND NEW.total_score IS NOT NULL THEN
        IF NEW.total_score >= 60 THEN
            SET NEW.status = '正常';
        ELSE
            SET NEW.status = '重修';
        END IF;
    END IF;
END //

DELIMITER ;


-- ============================================================
-- TRG6: trg_Student_BeforeUpdate — 学籍状态变更校验
-- 时机: BEFORE UPDATE ON student
-- 功能: 当学籍状态变更为"毕业"时，验证是否满足毕业条件
-- ============================================================
DELIMITER //

DROP TRIGGER IF EXISTS trg_Student_BeforeUpdate //

CREATE TRIGGER trg_Student_BeforeUpdate
BEFORE UPDATE ON student
FOR EACH ROW
BEGIN
    DECLARE v_completed_credits DECIMAL(5,1);
    DECLARE v_gpa DECIMAL(4,2);

    -- 仅当状态变更为"毕业"时校验
    IF NEW.status = '毕业' AND OLD.status != '毕业' THEN
        -- 获取已修学分
        SET v_completed_credits = fn_GetCompletedCredits(NEW.student_id);
        -- 获取累计GPA
        SET v_gpa = fn_GetStudentGPA(NEW.student_id);

        -- 毕业条件：学分达标 + 累计GPA ≥ 2.0（4.3制）
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
