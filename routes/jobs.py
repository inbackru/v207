"""
Jobs Blueprint
Routes: /job/<slug>, /job/<slug>/apply
"""
import os
import uuid
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, redirect, url_for, flash, current_app, render_template
from flask_login import current_user
from werkzeug.utils import secure_filename

from app import db, csrf

jobs_bp = Blueprint('jobs', __name__)

@jobs_bp.route('/job/<job_slug>')
def job_detail(job_slug):
    """Job detail page"""
    from models import Job

    try:
        job = Job.query.filter(Job.slug == job_slug, Job.is_active == True, Job.status == 'active').first_or_404()

        job.views_count = (job.views_count or 0) + 1
        db.session.commit()

        return render_template('vacancy_details.html', vacancy=job)

    except Exception as e:
        print(f"Job detail error: {e}")
        flash('Вакансия не найдена', 'error')
        return redirect(url_for('jobs.careers'))


@jobs_bp.route('/job/<job_slug>/apply', methods=['POST'])
def submit_job_application(job_slug):
    """Submit job application with resume"""
    from models import Job

    try:
        job = Job.query.filter(Job.slug == job_slug, Job.is_active == True, Job.status == 'active').first_or_404()

        candidate_name = request.form.get('candidate_name', '').strip()
        candidate_phone = request.form.get('candidate_phone', '').strip()
        candidate_email = request.form.get('candidate_email', '').strip()
        cover_letter = request.form.get('cover_letter', '').strip()

        if not candidate_name or not candidate_phone:
            flash('Имя и телефон обязательны для заполнения', 'error')
            return redirect(url_for('jobs.job_detail', job_slug=job_slug))

        phone_pattern = r'^[\+]?[0-9\s\-\(\)]{10,18}$'
        if not re.match(phone_pattern, candidate_phone):
            flash('Неверный формат номера телефона', 'error')
            return redirect(url_for('jobs.job_detail', job_slug=job_slug))

        resume_filename = None
        resume_file = request.files.get('resume_file')

        if resume_file and resume_file.filename:
            allowed_extensions = {'pdf', 'doc', 'docx', 'txt', 'rtf'}
            filename = resume_file.filename.lower()

            if not any(filename.endswith('.' + ext) for ext in allowed_extensions):
                flash('Неподдерживаемый формат файла. Используйте PDF, DOC, DOCX, TXT или RTF', 'error')
                return redirect(url_for('jobs.job_detail', job_slug=job_slug))

            resume_file.seek(0, 2)
            file_size = resume_file.tell()
            resume_file.seek(0)

            if file_size > 5 * 1024 * 1024:
                flash('Размер файла не должен превышать 5 МБ', 'error')
                return redirect(url_for('jobs.job_detail', job_slug=job_slug))

            file_extension = filename.split('.')[-1]
            unique_filename = f"{uuid.uuid4()}_{candidate_name.replace(' ', '_')}_{job.slug}.{file_extension}"
            resume_filename = secure_filename(unique_filename)

            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'resumes')
            os.makedirs(upload_dir, exist_ok=True)

            resume_path = os.path.join(upload_dir, resume_filename)
            resume_file.save(resume_path)

        try:
            from email_service import send_notification
            admin_subject = f"Новый отклик на вакансию: {job.title}"
            admin_message = (
                f'Поступил новый отклик на вакансию "{job.title}":\n\n'
                f'Кандидат: {candidate_name}\n'
                f'Телефон: {candidate_phone}\n'
                f'Email: {candidate_email or "Не указан"}\n\n'
                f'Сопроводительное письмо:\n{cover_letter or "Не указано"}\n\n'
                f'Резюме: {resume_filename or "Не прикреплено"}\n'
                f'Вакансия: {job.title}\n'
                f'Дата подачи: {datetime.now().strftime("%d.%m.%Y %H:%M")}'
            )
            send_notification(
                recipient_email="hr@inback.ru",
                subject=admin_subject,
                message=admin_message,
                notification_type="job_application"
            )

            if candidate_email:
                send_notification(
                    recipient_email=candidate_email,
                    subject=f"Спасибо за отклик на вакансию: {job.title}",
                    message=(
                        f'Здравствуйте, {candidate_name}!\n\n'
                        f'Спасибо за ваш отклик на вакансию "{job.title}" в компании InBack.\n\n'
                        f'Мы получили ваше резюме и рассмотрим его в ближайшее время.\n'
                        f'Если ваша кандидатура подойдёт, мы свяжемся с вами по телефону {candidate_phone}.\n\n'
                        f'С уважением,\nКоманда InBack'
                    ),
                    notification_type="application_confirmation"
                )
        except Exception as e:
            print(f"Notification error in job application: {e}")

        flash('Спасибо! Ваш отклик отправлен. Мы свяжемся с вами в ближайшее время.', 'success')
        return redirect(url_for('jobs.job_detail', job_slug=job_slug))

    except Exception as e:
        print(f"Job application error: {e}")
        flash('Произошла ошибка при отправке. Попробуйте ещё раз.', 'error')
        return redirect(url_for('jobs.job_detail', job_slug=job_slug))
