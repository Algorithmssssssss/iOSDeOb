import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship

from .db import Base


def gen_id() -> str:
    return uuid.uuid4().hex


class IPA(Base):
    __tablename__ = "ipas"

    id = Column(String, primary_key=True, default=gen_id)
    original_filename = Column(String, nullable=False)
    sha256 = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending, extracting, ready, failed
    error_message = Column(Text, nullable=True)
    objc_warnings_json = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    file_tree_nodes = relationship("FileTreeNode", back_populates="ipa", cascade="all, delete-orphan")
    plists = relationship("PlistRecord", back_populates="ipa", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="ipa", cascade="all, delete-orphan")
    objc_classes = relationship("ObjCClass", cascade="all, delete-orphan")
    symbols = relationship("SymbolEntry", cascade="all, delete-orphan")
    disasm_results = relationship("DisasmResult", cascade="all, delete-orphan")


class FileTreeNode(Base):
    __tablename__ = "file_tree_nodes"

    id = Column(String, primary_key=True, default=gen_id)
    ipa_id = Column(String, ForeignKey("ipas.id"), nullable=False)
    parent_path = Column(String, nullable=True)
    path = Column(String, nullable=False)  # path relative to Payload/, e.g. "MyApp.app/Info.plist"
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # "file" | "dir"
    size_bytes = Column(Integer, nullable=True)
    mime_guess = Column(String, nullable=True)
    is_main_binary = Column(Boolean, default=False)

    ipa = relationship("IPA", back_populates="file_tree_nodes")


class PlistRecord(Base):
    __tablename__ = "plists"

    id = Column(String, primary_key=True, default=gen_id)
    ipa_id = Column(String, ForeignKey("ipas.id"), nullable=False)
    node_path = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # "info" | "entitlements" | "other"
    parsed_json = Column(Text, nullable=False)  # JSON-encoded

    ipa = relationship("IPA", back_populates="plists")


class ObjCClass(Base):
    __tablename__ = "objc_classes"

    id = Column(String, primary_key=True, default=gen_id)
    ipa_id = Column(String, ForeignKey("ipas.id"), nullable=False)
    name = Column(String, nullable=False)
    superclass = Column(String, nullable=True)
    superclass_resolved = Column(Boolean, default=False)
    data_json = Column(Text, nullable=False)  # {instance_methods, class_methods, properties, protocols, ivars}


class SymbolEntry(Base):
    __tablename__ = "symbols"

    id = Column(String, primary_key=True, default=gen_id)
    ipa_id = Column(String, ForeignKey("ipas.id"), nullable=False)
    name = Column(String, nullable=False)
    address = Column(BigInteger, nullable=False)


class DisasmResult(Base):
    __tablename__ = "disasm_results"

    id = Column(String, primary_key=True, default=gen_id)
    ipa_id = Column(String, ForeignKey("ipas.id"), nullable=False)
    address = Column(BigInteger, nullable=False)
    name = Column(String, nullable=True)
    size = Column(Integer, nullable=True)
    signature = Column(String, nullable=True)
    data_json = Column(Text, nullable=False)  # {ops, calls_out, callers_in}


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=gen_id)
    ipa_id = Column(String, ForeignKey("ipas.id"), nullable=False)
    celery_task_id = Column(String, nullable=True)
    phase = Column(String, default="extract")
    context_address = Column(BigInteger, nullable=True)  # which function, for phase="disasm" jobs
    status = Column(String, default="queued")  # queued, running, done, failed
    progress_pct = Column(Integer, default=0)
    message = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    ipa = relationship("IPA", back_populates="jobs")
