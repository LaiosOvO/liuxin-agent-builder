"""agent-builder v1 API 路由包。

注册所有 v1 端点：
- workflows: Workflow CRUD + 草稿/发布/校验
- instances: Instance 创建/列表/详情/中止
- instances_events: GET /instances/{id}/events SSE 事件流（Plan 02-07）
"""
from fastapi import APIRouter

from app.agent_builder.api.v1 import instances, instances_events, workflows

router = APIRouter(prefix="/api/agent_builder/v1")
router.include_router(workflows.router)
router.include_router(instances.router)
router.include_router(instances_events.router)
