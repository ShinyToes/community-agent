"""Opt-in fictional business data; no accounts and no overwrites."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import College, Major, Class, Student, Teacher, Course, CourseOffering


def main():
    app = create_app()
    with app.app_context():
        if Student.query.first() or Teacher.query.first() or Course.query.first():
            raise SystemExit('已有学生、教师或课程；停止演示数据初始化，不覆盖现有数据。')
        college = College(college_code='DEMO', college_name='演示学院')
        db.session.add(college)
        db.session.flush()
        major = Major(major_code='DEMO', major_name='演示专业', duration=4,
                      degree_type='学士', college_id=college.college_id)
        db.session.add(major)
        db.session.flush()
        class_ = Class(class_name='演示班', grade=2026, major_id=major.major_id)
        teacher = Teacher(name='演示教师', college_id=college.college_id)
        course = Course(course_code='DEMO', course_name='演示数据库课程', credits=3,
                        hours=48, course_type='必修', college_id=college.college_id)
        db.session.add_all([class_, teacher, course])
        db.session.flush()
        db.session.add(Student(student_id='S2027001', name='演示学生', gender='男',
                               enrollment_year=2026, education_length=4, education_level='本科',
                               status='在读', major_id=major.major_id, class_id=class_.class_id))
        db.session.add(CourseOffering(course_id=course.course_id, teacher_id=teacher.teacher_id,
                                      academic_year='2026-2027', semester='第一学期',
                                      max_students=30, cur_students=0, schedule='周一1-2节'))
        db.session.commit()
        print('已创建虚构演示数据；可为学号 S2027001 单独创建账号。')


if __name__ == '__main__':
    main()
