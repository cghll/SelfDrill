"""阶段 1：数据模型约束测试。

这些约束是业务正确性的地基（一轮每题一次、一版本一题一份），
必须在数据库层生效，不能只靠应用层判断。
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.common.timeutil import utcnow
from app.db.models import (
    BankVersion,
    Question,
    QuestionBank,
    QuestionRevision,
    Round,
    RoundItem,
    User,
)

EXPECTED_TABLES = {
    "users",
    "question_banks",
    "bank_versions",
    "questions",
    "question_revisions",
    "import_previews",
    "rounds",
    "round_items",
    "round_advance_requests",
}


def test_all_expected_tables_created(db_session_factory) -> None:
    inspector = inspect(db_session_factory.kw["bind"])
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_username_is_unique(db_session_factory) -> None:
    with db_session_factory() as session:
        session.add(User(username="dup", password_hash="x"))
        session.commit()
    with db_session_factory() as session:
        session.add(User(username="dup", password_hash="y"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_round_item_position_unique_per_round(db_session_factory) -> None:
    with db_session_factory() as session:
        bank, version, revisions = _seed_bank(session, question_count=1)
        round_obj = Round(bank_id=bank.id, bank_version_id=version.id, round_number=1)
        session.add(round_obj)
        session.flush()
        session.add(RoundItem(round_id=round_obj.id, question_revision_id=revisions[0].id, position=0))
        session.commit()
        session.add(RoundItem(round_id=round_obj.id, question_revision_id=revisions[0].id, position=0))
        with pytest.raises(IntegrityError):
            session.commit()


def test_round_item_revision_unique_per_round(db_session_factory) -> None:
    """同一轮里同一道题不能出现两次，这是 FR-007 的数据库级保证。"""
    with db_session_factory() as session:
        bank, version, revisions = _seed_bank(session, question_count=1)
        round_obj = Round(bank_id=bank.id, bank_version_id=version.id, round_number=1)
        session.add(round_obj)
        session.flush()
        session.add(RoundItem(round_id=round_obj.id, question_revision_id=revisions[0].id, position=0))
        session.commit()
        session.add(RoundItem(round_id=round_obj.id, question_revision_id=revisions[0].id, position=1))
        with pytest.raises(IntegrityError):
            session.commit()


def test_bank_version_number_unique_per_bank(db_session_factory) -> None:
    with db_session_factory() as session:
        bank, _version, _revisions = _seed_bank(session, question_count=1)
        session.add(
            BankVersion(
                bank_id=bank.id,
                version_number=1,
                source_filename="a.md",
                source_hash="h",
                question_count=0,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_deleting_bank_cascades(db_session_factory) -> None:
    """删除题库必须清理版本、题目、修订和轮次，避免留下孤儿数据。"""
    with db_session_factory() as session:
        bank, version, revisions = _seed_bank(session, question_count=2)
        round_obj = Round(bank_id=bank.id, bank_version_id=version.id, round_number=1)
        session.add(round_obj)
        session.flush()
        session.add(
            RoundItem(round_id=round_obj.id, question_revision_id=revisions[0].id, position=0)
        )
        session.commit()

        session.delete(bank)
        session.commit()

        assert session.query(BankVersion).count() == 0
        assert session.query(Question).count() == 0
        assert session.query(QuestionRevision).count() == 0
        assert session.query(Round).count() == 0
        assert session.query(RoundItem).count() == 0


def _seed_bank(session, question_count: int):
    user = User(username=f"u-{utcnow().timestamp()}", password_hash="x")
    session.add(user)
    session.flush()
    bank = QuestionBank(user_id=user.id, name="测试题库")
    session.add(bank)
    session.flush()
    version = BankVersion(
        bank_id=bank.id,
        version_number=1,
        source_filename="sample.md",
        source_hash="hash",
        question_count=question_count,
    )
    session.add(version)
    session.flush()
    revisions = []
    for index in range(question_count):
        question = Question(bank_id=bank.id, stable_key=f"k{index}")
        session.add(question)
        session.flush()
        revision = QuestionRevision(
            question_id=question.id,
            bank_version_id=version.id,
            title=f"题目 {index}",
            answer_markdown="答案",
            heading_level=2,
            section_path=["章节"],
            content_hash=f"c{index}",
            source_anchor={"start_line": 1, "end_line": 2},
        )
        session.add(revision)
        revisions.append(revision)
    session.flush()
    return bank, version, revisions
