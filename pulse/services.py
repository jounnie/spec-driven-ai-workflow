import logging

from django.db import connection, transaction

logger = logging.getLogger(__name__)


def delete_project(project):
    """Delete ``project`` and its submissions, then purge the database file.

    The rows go in one transaction (the submissions through ``on_delete=CASCADE``).
    After the commit the WAL is checkpointed and truncated, and the database is
    vacuumed, so the deleted data is gone from the db file and its ``-wal`` file
    too (``secure_delete`` zeroes the freed pages). ``VACUUM`` cannot run inside
    a transaction, hence ``on_commit``. A failing purge is logged, never raised:
    the deletion stays committed.
    """
    project_id = project.pk
    with transaction.atomic():
        project.delete()
        transaction.on_commit(lambda: purge_database_file(project_id))


def purge_database_file(project_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            row = cursor.fetchone()
            if row is not None and row[0]:
                logger.warning(
                    'WAL checkpoint was busy after deleting project %s; data may remain in the WAL file.',
                    project_id,
                )
            cursor.execute('VACUUM')
    except Exception:
        logger.warning(
            'Purging the database file after deleting project %s failed.', project_id, exc_info=True
        )
