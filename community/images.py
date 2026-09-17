"""Private raster storage; public reads require a live current published revision."""
from io import BytesIO
from pathlib import Path
import re
import uuid
import warnings

from flask import Blueprint, abort, current_app, jsonify, request, send_file
from flask_login import current_user, login_required
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from .extensions import db
from .models import ImageAsset, Post, RevisionImage, User
from .security import consume_auth_attempt

bp = Blueprint('images', __name__)
MAX_SIZE = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000


def folder():
    return Path(current_app.config.get('IMAGE_FOLDER') or Path(current_app.instance_path) / 'images')


@bp.post('/images')
@login_required
def upload():
    consume_auth_attempt('image')
    file = request.files.get('file')
    if not file: abort(400, description='请选择一张图片。')
    raw = file.stream.read(MAX_SIZE + 1)
    if len(raw) > MAX_SIZE: abort(413, description='单张图片不能超过 5 MB。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as im:
                if im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'n_frames', 1) != 1:
                    abort(400, description='只支持静态 JPG、PNG、WebP 图片。')
                if im.width * im.height > MAX_PIXELS:
                    abort(400, description='图片不能超过1600万像素。')
                im.load()
                corrected = ImageOps.exif_transpose(im)
                # Re-encode pixels only: no EXIF, filename, appended payload or original metadata.
                clean = Image.new('RGBA' if 'A' in corrected.getbands() else 'RGB', corrected.size)
                clean.paste(corrected.convert(clean.mode))
                clean.thumbnail((2400, 2400))
                output = BytesIO(); clean.save(output, 'WEBP', quality=88)
                width, height = clean.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        abort(400, description='图片无法读取或尺寸异常，请换一张图片。')
    actor = db.session.scalar(select(User).where(User.id == current_user.id).with_for_update()
                              .execution_options(populate_existing=True))
    if not actor or not actor.active: abort(401)
    image_id = uuid.uuid4().hex
    root = folder(); root.mkdir(parents=True, exist_ok=True)
    path = root / (image_id + '.webp')
    data = output.getvalue()
    try:
        with path.open('xb') as target: target.write(data)
        db.session.add(ImageAsset(id=image_id, owner_id=actor.id, size=len(data), width=width, height=height))
        db.session.commit()
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise
    return jsonify(id=image_id, url='/images/' + image_id, width=width, height=height), 201


@bp.get('/images/<image_id>')
def read(image_id):
    if not re.fullmatch(r'[0-9a-f]{32}', image_id): abort(404)
    asset = db.session.get(ImageAsset, image_id)
    if not asset: abort(404)
    owned = current_user.is_authenticated and current_user.id == asset.owner_id
    if not owned:
        visible = db.session.scalar(select(Post.id).join(RevisionImage,
            RevisionImage.revision_id == Post.current_revision_id).where(
            RevisionImage.image_id == image_id, Post.status == 'published',
            Post.deleted_at.is_(None)).limit(1))
        if visible is None: abort(404)
    path = folder() / (image_id + '.webp')
    if not path.is_file(): abort(404)
    # Do not return 304/cacheable content: visibility may change after edits/deletion.
    return send_file(path, mimetype='image/webp', conditional=False, etag=False, max_age=0)
