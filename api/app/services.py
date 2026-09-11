"""Shared query logic used by more than one route module."""

import json

from sqlalchemy.orm import Session

from .models import ObjCClass, SymbolEntry


def get_merged_functions(db: Session, ipa_id: str) -> list[dict]:
    """Every named function for a scan: ObjC methods (from parsed class data)
    plus symbol-table C symbols, deduplicated by address and sorted by it."""
    functions: list[dict] = []
    seen_addresses: set[int] = set()

    for row in db.query(ObjCClass).filter(ObjCClass.ipa_id == ipa_id).all():
        data = json.loads(row.data_json)
        for m in data.get("instance_methods", []):
            if m.get("address") is not None and m["address"] not in seen_addresses:
                seen_addresses.add(m["address"])
                functions.append({
                    "address": m["address"],
                    "name": f"-[{row.name} {m['selector']}]",
                    "source": "objc_method",
                    "class_name": row.name,
                    "is_class_method": False,
                })
        for m in data.get("class_methods", []):
            if m.get("address") is not None and m["address"] not in seen_addresses:
                seen_addresses.add(m["address"])
                functions.append({
                    "address": m["address"],
                    "name": f"+[{row.name} {m['selector']}]",
                    "source": "objc_method",
                    "class_name": row.name,
                    "is_class_method": True,
                })

    for s in db.query(SymbolEntry).filter(SymbolEntry.ipa_id == ipa_id).all():
        if s.address not in seen_addresses:
            seen_addresses.add(s.address)
            functions.append({
                "address": s.address,
                "name": s.name,
                "source": "symbol",
                "class_name": None,
                "is_class_method": None,
            })

    functions.sort(key=lambda f: f["address"])
    return functions


def get_class_summary(row: ObjCClass) -> dict:
    data = json.loads(row.data_json)
    return {
        "name": row.name,
        "superclass": row.superclass,
        "instance_method_count": len(data.get("instance_methods", [])),
        "class_method_count": len(data.get("class_methods", [])),
        "property_count": len(data.get("properties", [])),
    }
