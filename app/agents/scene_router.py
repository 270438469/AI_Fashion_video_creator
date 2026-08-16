from app.domain.models import ProductAnalysis, SceneDecision, SceneScore


def overlap_score(left: list[str], right: list[str]) -> float:
    if not left:
        return 0.0
    left_set = {item.lower() for item in left}
    right_set = {item.lower() for item in right}
    direct = len(left_set & right_set)
    fuzzy = sum(1 for item in left_set if any(item in candidate or candidate in item for candidate in right_set))
    return min(1.0, max(direct, fuzzy) / max(1, min(3, len(left_set))))


class SceneRouter:
    def __init__(self, scenes: list[dict], config: dict):
        self.scenes = scenes
        self.config = config

    def route(self, analysis: ProductAnalysis) -> SceneDecision:
        weights = self.config["weights"]
        scores = []
        enriched_styles = list(analysis.style_tags) + [x for x in [analysis.category, analysis.subcategory, analysis.fit] if x]
        for scene in self.scenes:
            style = overlap_score(enriched_styles, scene.get("styles", []))
            occasion = overlap_score(analysis.occasion_tags, scene.get("occasions", []))
            color = 1.0 if analysis.primary_color.lower() in {c.lower() for c in scene.get("colors", [])} else 0.2
            season = overlap_score(analysis.season_tags, scene.get("seasons", []))
            utility = float(scene["ecommerce_utility"])
            final = style * weights["style"] + occasion * weights["occasion"] + color * weights["color"] + season * weights["season"] + utility * weights["ecommerce"]
            scores.append(SceneScore(scene_id=scene["id"], style_match=round(style, 4), occasion_match=round(occasion, 4),
                                     color_match=round(color, 4), season_match=round(season, 4), ecommerce_utility=utility,
                                     final_score=round(final, 4)))
        scores.sort(key=lambda item: (item.final_score, item.ecommerce_utility), reverse=True)
        if analysis.confidence < self.config["minimum_confidence"]:
            primary = self.config["fallback_scene"]
            reason = "Product confidence below threshold; safe studio fallback selected."
        else:
            primary = scores[0].scene_id
            reason = f"{primary} has the strongest configured style, occasion, color and season fit."
        backup = next((item.scene_id for item in scores if item.scene_id != primary), None)
        confidence = scores[0].final_score if primary != self.config["fallback_scene"] else max(analysis.confidence, scores[0].final_score)
        return SceneDecision(primary_scene=primary, backup_scene=backup, confidence=round(confidence, 4), rankings=scores, reason=reason)

