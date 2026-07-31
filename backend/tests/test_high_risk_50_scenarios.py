from __future__ import annotations

import pytest

from app.risk.classifier import assess_risk
from app.risk.schemas import HighRiskCreate
from app.risk.service import HighRiskService
from app.store import Store


SCENARIOS = [
    *(('medical', text) for text in (
        '医疗方案需要复核', '这个症状是否需要急救', '用药剂量如何核对', '药物相互作用风险', '诊断依据是否充分',
        'medical treatment review', 'diagnosis needs verification', 'medication safety check', '急救红旗判断', '医疗病史与过敏核对',
    )),
    *(('legal', text) for text in (
        '法律意见需要复核', '合同条款是否有效', '诉讼时效如何判断', '律师应核对哪些材料', '适用法域是什么',
        'legal advice review', 'lawsuit deadline analysis', 'jurisdiction must be confirmed', '法律责任与救济', '合同争议处理',
    )),
    *(('investment', text) for text in (
        '重大投资是否合适', '证券组合风险评估', '股票集中度过高吗', '基金流动性风险', '加密资产杠杆风险',
        'investment suitability review', 'trading risk assessment', 'portfolio loss tolerance', '投资数据时间核对', '杠杆投资是否可承受',
    )),
    *(('compliance', text) for text in (
        '合规放行需要什么证据', '监管规则版本核对', '审计例外能否批准', '政策豁免审批链', '合规控制责任人',
        'compliance evidence review', 'regulatory version check', '合规控制测试', '监管报告是否完整', '审计例外证据',
    )),
    *(('production_incident', text) for text in (
        '生产事故如何止损', '线上事故回滚条件', '生产环境数据库故障', '数据库泄漏处置', 'incident response review',
        'outage rollback plan', 'production failure triage', '生产事故证据保留', '线上事故客户影响', '生产环境变更审批',
    )),
]


@pytest.mark.parametrize(('expected_domain', 'question'), SCENARIOS)
async def test_fifty_high_risk_control_scenarios_fail_closed(tmp_path, expected_domain, question):
    assessment = assess_risk(question, f'classification-{expected_domain}')
    assert expected_domain in assessment.detected_domains
    assert assessment.risk_tier in {'high', 'critical'}
    assert assessment.requires_user_confirmation is True
    assert 0.5 <= assessment.confidence <= 0.95

    run_id = f"run-{expected_domain}-{abs(hash(question))}"
    store = Store(tmp_path / 'council.sqlite3')
    case = await HighRiskService(store, {}).create(
        HighRiskCreate(run_id=run_id, question=question),
        'requester-a',
    )
    assert case.status == 'MORE_INFORMATION_REQUIRED'
    assert case.required_facts
    assert all(item.required and item.materiality == 'critical' for item in case.required_facts)
    assert case.assurance.evidence_complete is False

