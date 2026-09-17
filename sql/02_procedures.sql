-- ============================================================
-- 学籍管理系统 - 存储过程 (Stored Procedures)
-- ============================================================

USE student_management_agent;

-- ============================================================
-- SP1: proc_EnrollStudent — 学生选课
-- 功能: 在事务中完成选课，检查课容量、时间冲突、重复选课
-- 参数: p_student_id (学号), p_offering_id (开课ID)
-- 返回: 成功或错误信息
-- ============================================================
DELIMITER //

DROP PROCEDURE IF EXISTS proc_EnrollStudent //

CREATE PROCEDURE proc_EnrollStudent(
    IN  p_student_id  VARCHAR(20),
    IN  p_offering_id INT,
    OUT p_result      VARCHAR(200)
)
proc_label: BEGIN
    DECLARE v_max_students  INT;
    DECLARE v_cur_students  INT;
    DECLARE v_enrolled       INT DEFAULT 0;
    DECLARE v_student_status VARCHAR(20);
    DECLARE v_has_conflict   TINYINT DEFAULT 0;

    -- 异常处理（仅处理未预期的SQL错误，不再自行管理事务）
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        SET p_result = '错误：选课失败，系统异常';
    END;

    -- 事务由调用方（Python）管理

    -- 1. 检查学生学籍状态是否正常
    SELECT status INTO v_student_status
    FROM student WHERE student_id = p_student_id FOR UPDATE;

    IF v_student_status IS NULL THEN
        SET p_result = '错误：学生不存在';
        LEAVE proc_label;
    ELSEIF v_student_status != '在读' THEN
        SET p_result = CONCAT('错误：学籍状态为"', v_student_status, '"，不允许选课');
        LEAVE proc_label;
    END IF;

    -- 2. 检查课程是否存在且有待选名额
    SELECT max_students, cur_students INTO v_max_students, v_cur_students
    FROM course_offering
    WHERE offering_id = p_offering_id
    FOR UPDATE;  -- 行级锁，防止并发超选

    IF v_max_students IS NULL THEN
        SET p_result = '错误：开课信息不存在';
        LEAVE proc_label;
    ELSEIF v_cur_students >= v_max_students THEN
        SET p_result = '错误：课程容量已满';
        LEAVE proc_label;
    END IF;

    -- 4. 检查是否已选过该课程（排除退课，因为上面已处理）
    SELECT COUNT(*) INTO v_enrolled
    FROM enrollment
    WHERE student_id = p_student_id AND offering_id = p_offering_id
      AND status != '退课';

    IF v_enrolled > 0 THEN
        SET p_result = '错误：已选过该课程，不可重复选课';
        LEAVE proc_label;
    END IF;

    -- Prevent duplicate active/passed enrollments in another offering of this course.
    SELECT COUNT(*) INTO v_enrolled
    FROM enrollment e JOIN course_offering co ON co.offering_id = e.offering_id
    WHERE e.student_id = p_student_id AND e.status IN ('在修', '已通过')
      AND co.course_id = (SELECT course_id FROM course_offering WHERE offering_id = p_offering_id);
    IF v_enrolled > 0 THEN
        SET p_result = '错误：已选过该课程的其他时间段，不可重复选课';
        LEAVE proc_label;
    END IF;

    -- 5. 检查时间冲突（只检查在修课程的历史冲突）
    SET v_has_conflict = fn_CheckCourseConflict(p_student_id, p_offering_id);
    IF v_has_conflict = 1 THEN
        SET p_result = '错误：与已有课程时间冲突';
        LEAVE proc_label;
    END IF;

    -- 3. 如果之前退过课，直接重新激活（避免重复键冲突）
    UPDATE enrollment
    SET status = '在修', enroll_date = NOW()
    WHERE student_id = p_student_id AND offering_id = p_offering_id
      AND status = '退课';

    IF ROW_COUNT() > 0 THEN
        -- 触发器不会对 UPDATE 触发，手动更新计数
        UPDATE course_offering
        SET cur_students = cur_students + 1
        WHERE offering_id = p_offering_id;
        SET p_result = '选课成功';
        LEAVE proc_label;
    END IF;


    -- 6. 插入选课记录（触发器 trg_Enrollment_AfterInsert 会自动更新 cur_students）
    INSERT INTO enrollment (student_id, offering_id, status)
    VALUES (p_student_id, p_offering_id, '在修');

    SET p_result = '选课成功';
END proc_label //

DELIMITER ;


-- ============================================================
-- SP2: proc_CalculateStudentGPA — 计算学生GPA
-- 功能: 计算指定学生在指定学期的GPA和累计GPA
-- ============================================================
DELIMITER //

DROP PROCEDURE IF EXISTS proc_CalculateStudentGPA //

CREATE PROCEDURE proc_CalculateStudentGPA(
    IN  p_student_id    VARCHAR(20),
    IN  p_academic_year VARCHAR(9),
    IN  p_semester      VARCHAR(10)
)
BEGIN
    SELECT
        e.student_id,
        co.academic_year,
        co.semester,
        ROUND(SUM(c.credits * g.gpa) / NULLIF(SUM(c.credits), 0), 2) AS semester_gpa,
        SUM(c.credits) AS semester_credits,
        COUNT(DISTINCT e.enrollment_id) AS course_count
    FROM enrollment e
    INNER JOIN grade g ON e.enrollment_id = g.enrollment_id
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id
      AND co.academic_year = p_academic_year
      AND co.semester = p_semester
      AND e.status IN ('已通过', '在修')
      AND g.gpa IS NOT NULL
    GROUP BY e.student_id, co.academic_year, co.semester;
END //

DELIMITER ;


-- ============================================================
-- SP3: proc_ChangeMajor — 专业变更
-- 功能: 事务保护下完成专业变更(更新学生专业+记录变更+更新班级)
-- ============================================================
DELIMITER //

DROP PROCEDURE IF EXISTS proc_ChangeMajor //

CREATE PROCEDURE proc_ChangeMajor(
    IN  p_student_id    VARCHAR(20),
    IN  p_new_major_id  INT,
    IN  p_new_class_id  INT,
    IN  p_reason        TEXT,
    IN  p_attachment    VARCHAR(255),
    OUT p_result        VARCHAR(200)
)
BEGIN
    DECLARE v_old_major_id INT;
    DECLARE v_old_class_id INT;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_result = '错误：专业变更失败，事务已回滚';
    END;

    START TRANSACTION;

    -- 1. 获取学生当前专业和班级
    SELECT major_id, class_id INTO v_old_major_id, v_old_class_id
    FROM student WHERE student_id = p_student_id;

    IF v_old_major_id IS NULL THEN
        SET p_result = '错误：学生不存在';
        ROLLBACK;
    END IF;

    -- 2. 验证目标专业和目标班级存在且匹配
    IF NOT EXISTS (
        SELECT 1 FROM class
        WHERE class_id = p_new_class_id AND major_id = p_new_major_id
    ) THEN
        SET p_result = '错误：目标班级不属于目标专业';
        ROLLBACK;
    END IF;

    -- 3. 更新学生专业和班级
    UPDATE student
    SET major_id = p_new_major_id,
        class_id = p_new_class_id,
        updated_at = NOW()
    WHERE student_id = p_student_id;

    -- 4. 记录专业变更历史
    INSERT INTO major_change (
        student_id, old_major_id, new_major_id,
        change_date, reason, approval_status,
        attachment
    ) VALUES (
        p_student_id, v_old_major_id, p_new_major_id,
        CURDATE(), p_reason, '已通过',
        p_attachment
    );

    COMMIT;
    SET p_result = '专业变更成功';
END //

DELIMITER ;


-- ============================================================
-- SP4: proc_GraduateAudit — 毕业资格审核
-- 功能: 检查学生是否满足毕业条件(必修学分+总学分+绩点)
-- ============================================================
DELIMITER //

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

    -- 获取学生信息
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

    -- 计算已获学分(状态为"已通过"的课程)
    SELECT IFNULL(SUM(c.credits), 0) INTO v_total_credits
    FROM enrollment e
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id AND e.status = '已通过';

    -- 计算累计GPA
    SELECT IFNULL(ROUND(SUM(c.credits * g.gpa) / NULLIF(SUM(c.credits), 0), 2), 0)
    INTO v_cumulative_gpa
    FROM enrollment e
    INNER JOIN grade g ON e.enrollment_id = g.enrollment_id
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id AND g.gpa IS NOT NULL;

    -- 统计未通过必修课数量
    SELECT COUNT(*) INTO v_failed_count
    FROM enrollment e
    INNER JOIN course_offering co ON e.offering_id = co.offering_id
    INNER JOIN course c ON co.course_id = c.course_id
    WHERE e.student_id = p_student_id
      AND c.course_type = '必修'
      AND e.status = '未通过';

    -- 判断毕业资格
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

DELIMITER ;
