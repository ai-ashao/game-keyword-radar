"""Manual validation records, independent of immutable scan snapshots."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import fcntl
from game_keyword_radar.models import ValidationRecord, utc_now
from game_keyword_radar.storage import SnapshotStore

class ValidationStore:
    def __init__(self, settings):
        self.root = settings.data_dir / 'validation'
    @staticmethod
    def key(record):
        return hashlib.sha256(f'{record.page_id}:{record.market}:{record.language}:{record.is_demo}'.encode()).hexdigest()
    def list(self):
        result=[]
        for path in sorted(self.root.glob('*.json')):
            try:
                result.append(ValidationRecord.model_validate_json(path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                raise ValueError(f'Validation record is unreadable: {path.name}; no records have been overwritten')
        return sorted(result,key=lambda r:r.updated_at,reverse=True)
    def save(self, record):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            record.updated_at=utc_now()
            record=ValidationRecord.model_validate(record.model_dump())
            SnapshotStore._atomic_json(self.root / f'{self.key(record)}.json',record.model_dump(mode='json'))
        return record
    def projected_pages(self, snapshot):
        records={r.page_id:r for r in self.list() if (r.market,r.language,r.is_demo)==(snapshot.country,snapshot.language,snapshot.is_demo)}
        pages=[]
        for page in snapshot.page_opportunities:
            row=page.model_dump(mode='json')
            if page.id in records:
                record=records[page.id]
                row['validation_record']=record.model_dump(mode='json')
                row['validation_status']=record.stage
            pages.append(row)
        return pages
