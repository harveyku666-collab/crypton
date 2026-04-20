"""Aggregate all sub-module routers under /api/v1."""

from fastapi import APIRouter

from app.market.router import router as market_router
from app.news.router import router as news_router
from app.analysis.router import router as analysis_router
from app.onchain.router import router as onchain_router
from app.ai.router import router as ai_router
from app.trading.router import router as trading_router
from app.briefing.router import router as briefing_router
from app.square.router import router as square_router
from app.address_intel.router import router as address_intel_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(market_router)
api_router.include_router(news_router)
api_router.include_router(analysis_router)
api_router.include_router(onchain_router)
api_router.include_router(ai_router)
api_router.include_router(trading_router)
api_router.include_router(briefing_router)
api_router.include_router(square_router)
api_router.include_router(address_intel_router)


@api_router.get("/system/endpoints", tags=["system"])
async def list_external_endpoints():
    """列出所有已注册的第三方 API 端点及安全属性"""
    from app.common.endpoints import ALL_ENDPOINTS
    return [
        {
            "name": ep.name,
            "base_url": ep.base_url,
            "description": ep.description,
            "data_direction": ep.data_direction,
            "allow_write": ep.allow_write,
            "sensitive": ep.sensitive,
        }
        for ep in ALL_ENDPOINTS
    ]


@api_router.get("/skills", tags=["skills"])
async def list_skills():
    """列出所有已融合的技能"""
    from app.common.skills import SKILLS
    return [
        {
            "id": s.id,
            "name": s.name,
            "name_zh": s.name_zh,
            "description": s.description,
            "description_zh": s.description_zh,
            "icon": s.icon,
            "category": s.category,
            "status": s.status,
            "api_endpoint": s.api_endpoint,
            "requires_credits": s.requires_credits,
            "features": s.features,
            "features_zh": s.features_zh,
            "data_sources": s.data_sources,
        }
        for s in SKILLS
    ]


@api_router.get("/skills/surf-pro", tags=["skills"])
async def get_surf_pro_modules():
    """获取 Surf 专业版子模块列表"""
    from app.common.skills import SURF_PRO_MODULES
    return SURF_PRO_MODULES


@api_router.get("/skills/{skill_id}", tags=["skills"])
async def get_skill(skill_id: str):
    """获取单个技能详情"""
    from app.common.skills import SKILL_MAP
    skill = SKILL_MAP.get(skill_id)
    if not skill:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return {
        "id": skill.id,
        "name": skill.name,
        "name_zh": skill.name_zh,
        "description": skill.description,
        "description_zh": skill.description_zh,
        "icon": skill.icon,
        "category": skill.category,
        "status": skill.status,
        "api_endpoint": skill.api_endpoint,
        "requires_credits": skill.requires_credits,
        "features": skill.features,
        "features_zh": skill.features_zh,
        "data_sources": skill.data_sources,
    }
