"""Repair the chat table if an earlier deployment recorded its migration without the table.

Some hosted SQLite instances have reported school_chatmessage missing even after the
0039 migration was present in migration history. This forward-only repair is safe on
healthy databases: it does nothing when the table already exists.
"""
from django.db import migrations


def ensure_chatmessage_table(apps, schema_editor):
    ChatMessage = apps.get_model("school", "ChatMessage")
    table_name = ChatMessage._meta.db_table
    existing_tables = set(schema_editor.connection.introspection.table_names())
    if table_name not in existing_tables:
        schema_editor.create_model(ChatMessage)


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0039_chatmessage"),
    ]

    operations = [
        migrations.RunPython(ensure_chatmessage_table, migrations.RunPython.noop),
    ]
