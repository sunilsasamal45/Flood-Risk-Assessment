"""
India Flood Risk Analyzer Agent
================================
Implements compound flood scoring combining:
  - River discharge (Open-Meteo GloFAS)
  - Extreme rainfall (IMD thresholds)
  - Cyclone/coastal surge risk
  - Soil-moisture saturation proxy
  - Historical monsoon calibration

Addresses PDF recommendations:
  * Compound flooding integration
  * Uncertainty / confidence communication
  * Local India/Odisha calibration
  * Human decision-support output
  * Resilient operation with stale-data detection
"""

import asyncio
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import logging

from .base_agent import BaseAgent, AgentInsight, AgentAlert

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IMD Rainfall Thresholds (mm/day)  — official classification
# ---------------------------------------------------------------------------
IMD_LIGHT        =  2.5
IMD_MODERATE     = 15.6
IMD_HEAVY        = 64.5
IMD_VERY_HEAVY   = 115.6
IMD_EXTREME      = 204.5

# ---------------------------------------------------------------------------
# India Regional Flood-Stage Calibration (CFS)
# Tuned for monsoon-season basins; values from CWC / CWPRS references
# ---------------------------------------------------------------------------
INDIA_FLOOD_STAGE_CALIBRATION = {
    "IN-GANGA":       70_000,
    "IN-BRAHMAPUTRA": 300_000,
    "IN-MAHANADI":    50_000,
    "IN-GODAVARI":    80_000,
    "IN-KRISHNA":     40_000,
    "IN-NARMADA":     30_000,
    "IN-KAVERI":      20_000,
    "IN-INDUS":       35_000,
    "DEFAULT":        50_000,
}

# Odisha-specific vulnerability multiplier (coastal + dense population)
ODISHA_VULNERABILITY_FACTOR = 1.25


def _notify(watershed_name: str, risk_level: str, risk_score: float,
            message: str, affected_areas: List[str] = None):
    """Fire-and-forget SMS wrapper."""
    try:
        from flood_prediction.notifications import send_sms_alert
        send_sms_alert(
            watershed_name=watershed_name,
            risk_level=risk_level,
            risk_score=risk_score,
            message=message,
            affected_areas=affected_areas or [],
        )
    except Exception as exc:
        logger.error(f"SMS notification failed in risk_analyzer: {exc}")


class RiskAnalyzerAgent(BaseAgent):
    """
    Advanced India flood risk analyzer.

    Compound risk score = weighted combination of:
      1. River discharge ratio  (40 %)
      2. Rainfall intensity     (30 %)
      3. Cyclone / surge factor (15 %)
      4. Soil saturation proxy  (15 %)

    Each component is 0–10; final score 0–10.
    Uncertainty band is derived from data freshness and source agreement.
    """

    def __init__(self):
        super().__init__(
            name="Risk Analyzer",
            description="AI compound flood risk analysis for India — river, rainfall, cyclone and coastal surge",
            check_interval=600,
        )
        self.risk_history: List[Dict[str, Any]] = []
        self.compound_history: List[Dict[str, Any]] = []
        self._previous_critical_count: int = 0

    # =========================================================================
    # BaseAgent interface
    # =========================================================================

    async def analyze(self, data: Dict[str, Any]) -> List[AgentInsight]:
        insights = []

        overall = await self._calculate_compound_risk(data)
        insights.append(AgentInsight(
            title="🎯 Compound Risk Level",
            value=f"{overall['level']} ({overall['score']:.1f}/10)",
            change=f"{overall['change']:+.1f} since last check",
            trend=overall['trend'],
            urgency=(
                'critical' if overall['score'] >= 8
                else 'high' if overall['score'] >= 6
                else 'normal'
            ),
        ))

        # Uncertainty band
        unc = overall['uncertainty']
        insights.append(AgentInsight(
            title="📊 Prediction Confidence",
            value=f"{overall['confidence']:.0f}%",
            change=f"±{unc:.1f} uncertainty band",
            trend='stable',
            urgency='high' if overall['confidence'] < 60 else 'normal',
        ))

        # Rainfall component
        rain = overall['components']['rainfall']
        insights.append(AgentInsight(
            title="🌧️ Rainfall Risk (IMD)",
            value=f"{rain['score']:.1f}/10",
            change=rain['description'],
            trend='up' if rain['score'] > 6 else 'stable',
            urgency='critical' if rain['score'] >= 8 else 'high' if rain['score'] >= 6 else 'normal',
        ))

        # River discharge component
        river = overall['components']['river']
        insights.append(AgentInsight(
            title="🌊 River Discharge Risk",
            value=f"{river['score']:.1f}/10",
            change=river['description'],
            trend='up' if river['trend'] == 'rising' else 'down' if river['trend'] == 'falling' else 'stable',
            urgency='critical' if river['score'] >= 8 else 'high' if river['score'] >= 6 else 'normal',
        ))

        # Cyclone / coastal surge component
        cyclone = overall['components']['cyclone']
        insights.append(AgentInsight(
            title="🌀 Cyclone / Coastal Risk",
            value=f"{cyclone['score']:.1f}/10",
            change=cyclone['description'],
            trend='up' if cyclone['score'] > 4 else 'stable',
            urgency='critical' if cyclone['score'] >= 7 else 'normal',
        ))

        # Critical watersheds
        critical_count = overall['critical_count']
        insights.append(AgentInsight(
            title="🚨 Critical Watersheds",
            value=f"{critical_count} sites",
            change=f"{critical_count - self._previous_critical_count:+d} from last check",
            trend='up' if critical_count > self._previous_critical_count else 'down' if critical_count < self._previous_critical_count else 'stable',
            urgency='critical' if critical_count > 5 else 'high' if critical_count > 2 else 'normal',
        ))

        # Peak risk window
        peak = await self._predict_peak_risk(data, overall)
        if peak:
            insights.append(AgentInsight(
                title="⏰ Peak Risk Window",
                value=peak['window'],
                change=f"{peak['confidence']:.0f}% confidence — {peak['recommended_action']}",
                trend='up',
                urgency='high',
            ))

        # Data staleness warning  (PDF: reliable data pipeline)
        stale = self._check_data_staleness(data)
        if stale['stale']:
            insights.append(AgentInsight(
                title="⚠️ Data Freshness Warning",
                value=f"Last update: {stale['age_minutes']:.0f} min ago",
                change="Showing cached data — treat predictions with caution",
                trend='stable',
                urgency='high',
            ))

        return insights

    async def check_alerts(self, data: Dict[str, Any]) -> List[AgentAlert]:
        alerts = []

        overall = await self._calculate_compound_risk(data)

        # ── Compound flood alert ──────────────────────────────────────────
        if overall['score'] >= 7 and overall['compound_event']:
            alert = AgentAlert(
                id=f"compound_flood_{datetime.now().strftime('%Y%m%d%H%M')}",
                title="🌊🌧️ COMPOUND FLOOD EVENT DETECTED",
                message=(
                    f"Simultaneous high river discharge AND heavy rainfall detected "
                    f"in {len(overall['compound_areas'])} watersheds. "
                    f"Compound risk score: {overall['score']:.1f}/10 [{overall['level']}]. "
                    f"Confidence: {overall['confidence']:.0f}%."
                ),
                severity="critical",
                source_agent=self.name,
                affected_areas=overall['compound_areas'],
                recommendations=[
                    "IMMEDIATE: Alert NDMA and State Disaster Management Authority",
                    "Deploy NDRF teams to compound-flood zones",
                    "Issue mandatory evacuation for low-lying river confluence areas",
                    "Activate SACHET mass-alert broadcast",
                    "Pre-position boats and rescue equipment at identified staging areas",
                    "Monitor CWC flood forecast every 30 minutes",
                    f"Data confidence: {overall['confidence']:.0f}% — cross-verify with IMD bulletin",
                ],
            )
            alerts.append(alert)
            for area in overall['compound_areas'][:3]:
                _notify(area, "CRITICAL", overall['score'], alert.message, overall['compound_areas'])

        # ── Rapid risk escalation ─────────────────────────────────────────
        escalation = self._detect_rapid_escalation(data)
        if escalation['rapid']:
            alert = AgentAlert(
                id=f"rapid_escalation_{datetime.now().strftime('%Y%m%d%H%M')}",
                title="⚡ Rapid Risk Escalation",
                message=(
                    f"River levels rising rapidly at {len(escalation['areas'])} sites. "
                    f"Average rate: {escalation['rate']:.0f} CFS/hr. "
                    f"Flash flood conditions possible within {escalation['eta_hours']:.1f} hours."
                ),
                severity="critical",
                source_agent=self.name,
                affected_areas=escalation['areas'],
                recommendations=[
                    "Immediately alert District Collectors of affected districts",
                    "Issue public advisory via Doordarshan and AIR",
                    "Pre-position NDRF rescue boats",
                    "Close low-lying bridges and causeways",
                    f"Next review in 30 minutes — current confidence {overall['confidence']:.0f}%",
                ],
            )
            alerts.append(alert)
            if escalation['areas']:
                _notify(
                    escalation['areas'][0], "HIGH",
                    min(10, escalation['rate'] / 100 + 6),
                    alert.message, escalation['areas'],
                )

        # ── Critical threshold breaches ───────────────────────────────────
        breaches = self._check_threshold_breaches(data)
        if breaches:
            breach_names = [b['watershed'] for b in breaches]
            alert = AgentAlert(
                id=f"threshold_breach_{datetime.now().strftime('%Y%m%d%H')}",
                title="🚨 Flood Stage Threshold Exceeded",
                message=(
                    f"{len(breaches)} river sites have exceeded critical flood-stage thresholds: "
                    f"{', '.join(breach_names[:4])}."
                    + (" and more." if len(breaches) > 4 else "")
                ),
                severity="critical",
                source_agent=self.name,
                affected_areas=breach_names,
                recommendations=[
                    "Immediate evacuation assessment for all flood-stage-breach zones",
                    "Coordinate with CWC Flood Monitoring Centre",
                    "Activate district EOCs (Emergency Operations Centres)",
                    "Ensure NDRF battalion on standby",
                    "Document and report to NDMA portal",
                ],
            )
            alerts.append(alert)
            for b in breaches:
                _notify(b['watershed'], "CRITICAL", b['value'],
                        f"Flood stage exceeded at {b['watershed']}", [b['watershed']])
            self._try_auto_pdf(data)

        # ── Cyclone coastal surge warning ─────────────────────────────────
        cyclone_risk = overall['components']['cyclone']
        if cyclone_risk['score'] >= 7:
            alerts.append(AgentAlert(
                id=f"cyclone_surge_{datetime.now().strftime('%Y%m%d%H')}",
                title="🌀 Cyclone / Coastal Surge Risk",
                message=(
                    f"Elevated coastal surge risk detected (score {cyclone_risk['score']:.1f}/10). "
                    f"{cyclone_risk['description']}. "
                    f"Coastal Odisha, Andhra Pradesh and West Bengal areas at risk."
                ),
                severity="critical",
                source_agent=self.name,
                affected_areas=["Odisha Coast", "Andhra Pradesh Coast", "West Bengal Coast"],
                recommendations=[
                    "Alert IMD Cyclone Warning Division",
                    "Activate coastal district disaster plans",
                    "Evacuate fishing communities from sea",
                    "Issue storm-surge inundation maps via INCOIS",
                    "Coordinate with Indian Navy / Coast Guard",
                ],
            ))

        # ── Pattern anomaly ───────────────────────────────────────────────
        if self._detect_pattern_anomaly(data):
            alerts.append(AgentAlert(
                id=f"anomaly_{datetime.now().strftime('%Y%m%d%H')}",
                title="🔍 Unusual Flood Pattern Detected",
                message=(
                    "AI detected an unusual combination of high risk scores and low river discharge. "
                    "This may indicate data quality issues, a localised cloudburst, or an unreported dam release."
                ),
                severity="warning",
                source_agent=self.name,
                recommendations=[
                    "Cross-check with IMD district-level rainfall bulletin",
                    "Contact CWC reservoir operations for dam release status",
                    "Increase monitoring frequency to every 15 minutes",
                    "Do NOT issue public alerts until data is verified",
                ],
            ))

        self._previous_critical_count = overall['critical_count']
        return alerts

    # =========================================================================
    # Compound flood scoring  (core India logic)
    # =========================================================================

    async def _calculate_compound_risk(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compound flood score = weighted combination of four hazard components.
        Returns score 0-10 with uncertainty band and confidence %.
        """
        watersheds = data.get('watersheds', [])
        imd_data   = data.get('imd_data', {})

        if not watersheds:
            return self._empty_risk()

        # --- Component 1: River discharge (40%) ---
        river_comp = self._score_river_discharge(watersheds)

        # --- Component 2: Rainfall intensity (30%) ---
        rain_comp = self._score_rainfall(watersheds, imd_data)

        # --- Component 3: Cyclone / coastal surge (15%) ---
        cyclone_comp = self._score_cyclone_risk(watersheds, imd_data)

        # --- Component 4: Soil saturation proxy (15%) ---
        soil_comp = self._score_soil_saturation(watersheds, rain_comp['cumulative_mm'])

        # Weighted composite
        score = (
            river_comp['score']   * 0.40 +
            rain_comp['score']    * 0.30 +
            cyclone_comp['score'] * 0.15 +
            soil_comp['score']    * 0.15
        )
        score = min(10.0, max(0.0, score))

        # Odisha vulnerability boost
        odisha_count = sum(
            1 for w in watersheds
            if 'odisha' in w.get('name', '').lower() or
               w.get('region_code', '') in ('IN-MAHANADI',)
        )
        if odisha_count > 0:
            score = min(10.0, score * ODISHA_VULNERABILITY_FACTOR)

        # Risk level
        level = (
            "CRITICAL" if score >= 8 else
            "HIGH"     if score >= 6 else
            "MODERATE" if score >= 4 else
            "LOW"
        )

        # Confidence and uncertainty (PDF: uncertainty communication)
        confidence, uncertainty = self._calculate_confidence(data, watersheds)

        # Change from history
        change = 0.0
        trend  = 'stable'
        if self.risk_history:
            prev = self.risk_history[-1]['score']
            change = score - prev
            trend = 'up' if change > 0.3 else 'down' if change < -0.3 else 'stable'

        # Compound event flag
        compound_event = (river_comp['score'] >= 6 and rain_comp['score'] >= 6)
        compound_areas = [
            w.get('name', '?') for w in watersheds
            if w.get('risk_score', 0) >= 6
        ][:8]

        # Critical count
        critical_count = sum(1 for w in watersheds if w.get('risk_score', 0) >= 8)

        # Store history
        self.risk_history.append({
            'timestamp': datetime.now(timezone.utc),
            'score': score, 'level': level,
        })
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self.risk_history = [h for h in self.risk_history if h['timestamp'] > cutoff]

        return {
            'score':          score,
            'level':          level,
            'change':         change,
            'trend':          trend,
            'confidence':     confidence,
            'uncertainty':    uncertainty,
            'compound_event': compound_event,
            'compound_areas': compound_areas,
            'critical_count': critical_count,
            'components': {
                'river':   river_comp,
                'rainfall': rain_comp,
                'cyclone': cyclone_comp,
                'soil':    soil_comp,
            },
        }

    def _score_river_discharge(self, watersheds: List[Dict]) -> Dict[str, Any]:
        """Score based on river discharge vs flood stage."""
        if not watersheds:
            return {'score': 0, 'description': 'No data', 'trend': 'stable', 'max_ratio': 0}

        ratios = []
        rising_count = 0
        for w in watersheds:
            flow  = w.get('current_streamflow_cfs', 0) or 0
            stage = w.get('flood_stage_cfs', 0) or 0
            if stage <= 0:
                # Use regional calibration
                stage = INDIA_FLOOD_STAGE_CALIBRATION.get(
                    w.get('region_code', 'DEFAULT'),
                    INDIA_FLOOD_STAGE_CALIBRATION['DEFAULT']
                )
            ratio = flow / stage if stage > 0 else 0
            ratios.append(ratio)
            if w.get('trend') == 'rising':
                rising_count += 1

        max_ratio = max(ratios) if ratios else 0
        avg_ratio = sum(ratios) / len(ratios)

        # Score: 0 at 0 ratio, 10 at ratio ≥ 1.3
        score = min(10.0, max_ratio * 8.0 + avg_ratio * 2.0)
        trend = 'rising' if rising_count > len(watersheds) * 0.4 else 'stable'
        above_stage = sum(1 for r in ratios if r >= 1.0)

        return {
            'score':       round(score, 2),
            'max_ratio':   round(max_ratio, 3),
            'avg_ratio':   round(avg_ratio, 3),
            'above_stage': above_stage,
            'rising_count': rising_count,
            'trend':       trend,
            'description': (
                f"{above_stage} sites above flood stage, "
                f"max ratio {max_ratio:.1%}, {rising_count} rising"
            ),
        }

    def _score_rainfall(self, watersheds: List[Dict], imd_data: Dict) -> Dict[str, Any]:
        """Score based on IMD rainfall intensity thresholds."""
        # Pull daily precipitation from watershed data if available
        precip_values = []
        for w in watersheds:
            p = w.get('daily_precipitation_mm') or w.get('precipitation_mm', 0)
            if p:
                precip_values.append(float(p))

        # Fallback: use imd_data forecasts
        if not precip_values and isinstance(imd_data, dict):
            for key, val in imd_data.items():
                if isinstance(val, dict):
                    p = val.get('max_precip', 0) or val.get('precipitation_mm', 0)
                    if p:
                        precip_values.append(float(p))

        if not precip_values:
            return {
                'score': 0, 'max_mm': 0, 'cumulative_mm': 0,
                'category': 'No data', 'description': 'Rainfall data unavailable'
            }

        max_mm  = max(precip_values)
        cumulative_mm = sum(precip_values)

        # IMD category scoring
        if max_mm >= IMD_EXTREME:
            score = 10.0; category = "Extremely Heavy (IMD Red)"
        elif max_mm >= IMD_VERY_HEAVY:
            score = 8.5 + (max_mm - IMD_VERY_HEAVY) / (IMD_EXTREME - IMD_VERY_HEAVY) * 1.5
            category = "Very Heavy (IMD Orange)"
        elif max_mm >= IMD_HEAVY:
            score = 6.0 + (max_mm - IMD_HEAVY) / (IMD_VERY_HEAVY - IMD_HEAVY) * 2.5
            category = "Heavy (IMD Yellow)"
        elif max_mm >= IMD_MODERATE:
            score = 3.0 + (max_mm - IMD_MODERATE) / (IMD_HEAVY - IMD_MODERATE) * 3.0
            category = "Moderate Rain"
        elif max_mm >= IMD_LIGHT:
            score = 1.0 + (max_mm - IMD_LIGHT) / (IMD_MODERATE - IMD_LIGHT) * 2.0
            category = "Light Rain"
        else:
            score = 0.0; category = "No significant rain"

        return {
            'score':          round(min(10.0, score), 2),
            'max_mm':         round(max_mm, 1),
            'cumulative_mm':  round(cumulative_mm, 1),
            'category':       category,
            'description':    f"{max_mm:.0f}mm/day — {category}",
        }

    def _score_cyclone_risk(self, watersheds: List[Dict], imd_data: Dict) -> Dict[str, Any]:
        """
        Score cyclone / coastal surge risk.
        Uses wind speed and coastal proximity from imd_data if available.
        Falls back to seasonal heuristic (June–Nov = active cyclone season).
        """
        month = datetime.now(timezone.utc).month

        # Bay of Bengal cyclone season: Apr–Dec peak Oct–Nov
        # Arabian Sea cyclone season: May–Jun, Oct–Nov
        seasonal_base = 0.0
        if month in (5, 6):       seasonal_base = 2.5  # Pre-monsoon, Arabian Sea
        elif month in (10, 11):   seasonal_base = 4.0  # Post-monsoon, Bay of Bengal peak
        elif month in (7, 8, 9):  seasonal_base = 1.5  # Monsoon season
        elif month in (4, 12):    seasonal_base = 1.0

        # Check imd_data for wind speed / storm info
        max_wind = 0.0
        if isinstance(imd_data, dict):
            for key, val in imd_data.items():
                if isinstance(val, dict):
                    w = val.get('wind_speed_kmh', 0) or val.get('wind_kmh', 0)
                    if w:
                        max_wind = max(max_wind, float(w))

        # Beaufort-to-risk scoring
        wind_score = 0.0
        if max_wind >= 220:   wind_score = 10.0; cat = "Super Cyclone"
        elif max_wind >= 165: wind_score = 8.5;  cat = "Very Severe Cyclone"
        elif max_wind >= 120: wind_score = 7.0;  cat = "Severe Cyclone"
        elif max_wind >= 88:  wind_score = 5.5;  cat = "Cyclone"
        elif max_wind >= 62:  wind_score = 3.5;  cat = "Deep Depression"
        elif max_wind >= 32:  wind_score = 2.0;  cat = "Depression"
        else:                 wind_score = 0.0;  cat = "Clear"

        # Coastal watershed proximity boost
        coastal_regions = {'IN-MAHANADI', 'IN-GODAVARI', 'IN-KRISHNA', 'IN-KAVERI'}
        coastal_count = sum(
            1 for w in watersheds
            if w.get('region_code', '') in coastal_regions
        )
        coastal_boost = min(2.0, coastal_count * 0.3)

        score = min(10.0, max(seasonal_base, wind_score) + coastal_boost)

        return {
            'score':       round(score, 2),
            'wind_kmh':    max_wind,
            'category':    cat if max_wind > 0 else f"Seasonal base (month {month})",
            'description': (
                f"{cat} {max_wind:.0f} km/h" if max_wind > 0
                else f"Seasonal cyclone risk (score {score:.1f})"
            ),
        }

    def _score_soil_saturation(self, watersheds: List[Dict], cumulative_rain_mm: float) -> Dict[str, Any]:
        """
        Soil saturation proxy:
        Uses cumulative rainfall as a proxy for antecedent moisture.
        High pre-monsoon saturation → reduced infiltration → higher runoff.
        """
        # Count watersheds that have been 'rising' for extended period
        sustained_rising = sum(
            1 for w in watersheds
            if w.get('trend') == 'rising' and
               abs(w.get('trend_rate_cfs_per_hour', 0)) > 50
        )

        # Saturation index: cumulative rain + sustained rise
        saturation_index = (cumulative_rain_mm / 300.0) * 5.0  # 300mm → half scale
        rise_contribution = min(3.0, sustained_rising * 0.5)

        score = min(10.0, saturation_index + rise_contribution)

        category = (
            "Saturated"      if score >= 7 else
            "Near-saturated" if score >= 5 else
            "Moist"          if score >= 3 else
            "Dry/Normal"
        )
        return {
            'score':       round(score, 2),
            'category':    category,
            'description': f"Soil: {category}, sustained-rising sites: {sustained_rising}",
        }

    # =========================================================================
    # Confidence & Uncertainty  (PDF: uncertainty communication)
    # =========================================================================

    def _calculate_confidence(
        self, data: Dict, watersheds: List[Dict]
    ) -> Tuple[float, float]:
        """
        Returns (confidence_pct, uncertainty_score_0to10).
        Factors:
          - Data freshness (age of last_updated)
          - Source agreement (openmeteo vs sample)
          - Number of real-data sites vs total
        """
        if not watersheds:
            return 30.0, 5.0

        total = len(watersheds)
        # Freshness score
        fresh = sum(1 for w in watersheds if self._is_fresh(w))
        freshness_factor = fresh / total

        # Source quality
        real_sources = sum(1 for w in watersheds if w.get('data_source') == 'openmeteo')
        source_factor = real_sources / total

        # Stale penalty
        stale = self._check_data_staleness(data)
        stale_penalty = 20 if stale['stale'] else 0

        # Component agreement (river vs rainfall directional consistency)
        confidence_raw = (freshness_factor * 50 + source_factor * 40 + 10) - stale_penalty
        confidence = max(20.0, min(95.0, confidence_raw))

        # Uncertainty = inverse of confidence, scaled 0-10
        uncertainty = round((100 - confidence) / 10, 1)

        return round(confidence, 1), uncertainty

    def _check_data_staleness(self, data: Dict) -> Dict[str, Any]:
        """Detect if primary data is stale — PDF: reliable data pipeline."""
        watersheds = data.get('watersheds', [])
        if not watersheds:
            return {'stale': False, 'age_minutes': 0}

        ages = []
        for w in watersheds:
            lu = w.get('last_updated', '')
            try:
                t = datetime.fromisoformat(lu.replace('Z', '+00:00'))
                ages.append((datetime.now(timezone.utc) - t).total_seconds() / 60)
            except Exception:
                pass

        if not ages:
            return {'stale': False, 'age_minutes': 0}

        max_age = max(ages)
        stale = max_age > 90  # 90 minutes threshold
        return {'stale': stale, 'age_minutes': round(max_age, 0)}

    def _is_fresh(self, watershed: Dict) -> bool:
        lu = watershed.get('last_updated', '')
        try:
            t = datetime.fromisoformat(lu.replace('Z', '+00:00'))
            return (datetime.now(timezone.utc) - t) < timedelta(hours=2)
        except Exception:
            return False

    # =========================================================================
    # Alert helpers
    # =========================================================================

    def _detect_rapid_escalation(self, data: Dict) -> Dict[str, Any]:
        areas = []
        max_rate = 0
        for w in data.get('watersheds', []):
            rate = abs(w.get('trend_rate_cfs_per_hour', 0) or 0)
            if rate > 150 and w.get('trend') == 'rising':
                areas.append(w.get('name', '?'))
                max_rate = max(max_rate, rate)

        # ETA to flood stage (hours)
        eta = 99.0
        for w in data.get('watersheds', []):
            flow  = w.get('current_streamflow_cfs', 0) or 0
            stage = w.get('flood_stage_cfs', 0) or INDIA_FLOOD_STAGE_CALIBRATION['DEFAULT']
            rate  = w.get('trend_rate_cfs_per_hour', 0) or 0
            if rate > 0 and flow < stage:
                eta = min(eta, (stage - flow) / rate)

        return {
            'rapid': len(areas) > 0,
            'areas': areas,
            'rate':  max_rate,
            'eta_hours': eta if eta < 99 else 24,
        }

    def _check_threshold_breaches(self, data: Dict) -> List[Dict]:
        breaches = []
        for w in data.get('watersheds', []):
            score = w.get('risk_score', 0)
            flow  = w.get('current_streamflow_cfs', 0) or 0
            stage = w.get('flood_stage_cfs', 0) or INDIA_FLOOD_STAGE_CALIBRATION['DEFAULT']

            if score >= 9:
                breaches.append({'watershed': w.get('name', '?'), 'type': 'risk_score', 'value': score})
            elif stage and flow >= stage * 0.9:
                breaches.append({'watershed': w.get('name', '?'), 'type': 'flood_stage', 'value': round(flow / stage, 2)})
        return breaches

    def _detect_pattern_anomaly(self, data: Dict) -> bool:
        ws = data.get('watersheds', [])
        if not ws:
            return False
        anomalous = sum(
            1 for w in ws
            if w.get('risk_score', 0) > 7 and w.get('current_streamflow_cfs', 0) < 100
        )
        return anomalous > len(ws) * 0.2

    async def _predict_peak_risk(
        self, data: Dict, overall: Dict
    ) -> Optional[Dict[str, Any]]:
        if len(self.risk_history) < 3:
            return None
        recent = self.risk_history[-4:]
        scores = [h['score'] for h in recent]
        if scores[-1] <= scores[0]:
            return None  # not rising
        rate = (scores[-1] - scores[0]) / max(len(scores) - 1, 1)
        if rate < 0.3:
            return None
        hours = max(1, int((10 - scores[-1]) / rate))
        confidence = min(85, 50 + overall['confidence'] * 0.35)
        action = (
            "Deploy NDRF NOW" if overall['score'] >= 7
            else "Prepare evacuation plans"
        )
        return {
            'window':             f"Next {hours}–{hours+3} hours",
            'confidence':         confidence,
            'recommended_action': action,
        }

    def _try_auto_pdf(self, data: Dict):
        try:
            from flood_prediction.settings import settings as _s
            if not getattr(_s, 'auto_pdf_on_critical', False):
                return
            from flood_prediction.notifications import generate_flood_report
            ws = data.get('watersheds', [])
            if ws:
                path = generate_flood_report(
                    watersheds=ws,
                    report_title="India Flood Intelligence — CRITICAL ALERT Report",
                )
                if path:
                    logger.info(f"Auto-generated critical alert PDF: {path}")
        except Exception as exc:
            logger.error(f"Auto PDF generation failed: {exc}")

    @staticmethod
    def _empty_risk() -> Dict[str, Any]:
        empty_comp = {'score': 0, 'description': 'No data', 'trend': 'stable',
                      'max_ratio': 0, 'category': 'Unknown', 'cumulative_mm': 0,
                      'wind_kmh': 0, 'rising_count': 0}
        return {
            'score': 0, 'level': 'UNKNOWN', 'change': 0, 'trend': 'stable',
            'confidence': 0, 'uncertainty': 10, 'compound_event': False,
            'compound_areas': [], 'critical_count': 0,
            'components': {
                'river': empty_comp, 'rainfall': empty_comp,
                'cyclone': empty_comp, 'soil': empty_comp,
            },
        }
