"""Read-only source-code weekday discovery; no database access."""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from loomera.globalization.weekday_rehearsal import discover_weekday_sources


class Command(BaseCommand):
    help = "List weekday-related source files and counts, never business records."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        candidates = discover_weekday_sources(Path(settings.BASE_DIR))
        data = {
            "candidate_source_files": len(candidates),
            "candidate_token_occurrences": sum(count for _, count in candidates),
            "candidate_paths": [path for path, _ in candidates],
            "database_access": False,
            "writes_performed": 0,
            "inventory_semantics_complete": False,
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(data, sort_keys=True, ensure_ascii=False))
        else:
            self.stdout.write(
                f"{data['candidate_source_files']} weekday candidate source files; "
                "static inventory only, no database reads or writes."
            )
