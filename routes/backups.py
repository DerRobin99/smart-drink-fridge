import os
from translation import translate
from utils.render import get_language

from flask import Blueprint, flash, redirect, send_from_directory

from backup import create_managed_backup, restore_backup
from database import DB, get_setting
from utils.auth import settings_admin_required


backup_bp = Blueprint("backups", __name__)


@backup_bp.post("/settings/backup/create")
@settings_admin_required
def backup_create():
    create_managed_backup("manual")

    flash(translate("backup_created_success", get_language()), "success")
    return redirect("/einstellungen#backup")


@backup_bp.get("/settings/backup/download/<filename>")
@settings_admin_required
def backup_download(filename):
    backup_path = get_setting("backup_path", "/data/backups")
    filename = os.path.basename(filename)
    file_path = os.path.join(backup_path, filename)

    if not os.path.isfile(file_path):
        flash(translate("backup_not_found", get_language()), "error")
        return redirect("/einstellungen#backup")

    return send_from_directory(
        backup_path,
        filename,
        as_attachment=True,
    )


@backup_bp.post("/settings/backup/delete/<filename>")
@settings_admin_required
def backup_delete(filename):
    backup_path = get_setting("backup_path", "/data/backups")
    filename = os.path.basename(filename)
    file_path = os.path.join(backup_path, filename)

    if os.path.isfile(file_path):
        os.remove(file_path)
        flash(translate("backup_deleted_success", get_language()), "success")
    else:
        flash(translate("backup_not_found", get_language()), "error")

    return redirect("/einstellungen#backup")


@backup_bp.post("/settings/backup/restore/<filename>")
@settings_admin_required
def backup_restore(filename):
    backup_path = get_setting("backup_path", "/data/backups")
    filename = os.path.basename(filename)

    backup_file = os.path.join(backup_path, filename)
    if not os.path.isfile(backup_file):
        flash(translate("backup_not_found", get_language()), "error")
        return redirect("/einstellungen#backup")

    restore_backup(backup_file, DB)

    flash(translate("backup_restored_success", get_language()), "success")
    return redirect("/einstellungen#backup")
