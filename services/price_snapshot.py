"""
Price Snapshot Service
Records monthly price history snapshots for residential complexes.
Called by APScheduler to keep price_history table fresh.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def record_price_snapshots():
    """
    For each active residential complex, compute avg/min/max price
    from current active properties and upsert a PriceHistory record
    for the current month/year.
    """
    from app import app, db
    from models import ResidentialComplex, Property, PriceHistory
    from sqlalchemy import func

    with app.app_context():
        try:
            now = datetime.utcnow()
            month = now.month
            year = now.year

            complexes = ResidentialComplex.query.filter_by(is_active=True).all()
            saved = 0
            skipped = 0

            for rc in complexes:
                try:
                    props = Property.query.filter_by(
                        complex_id=rc.id, is_active=True
                    ).filter(Property.price.isnot(None), Property.price > 0).all()

                    if not props:
                        skipped += 1
                        continue

                    prices = [p.price for p in props]
                    ppsm_list = [p.price_per_sqm for p in props if p.price_per_sqm and p.price_per_sqm > 0]

                    avg_price = int(sum(prices) / len(prices))
                    min_price = min(prices)
                    max_price = max(prices)
                    avg_ppsm = int(sum(ppsm_list) / len(ppsm_list)) if ppsm_list else (
                        int(avg_price / (sum(p.area for p in props if p.area) / max(len([p for p in props if p.area]), 1)))
                        if any(p.area for p in props) else None
                    )
                    count = len(prices)

                    existing = PriceHistory.query.filter_by(
                        complex_id=rc.id,
                        record_type='complex',
                        month=month,
                        year=year,
                    ).first()

                    if existing:
                        prev_avg = existing.avg_price
                        existing.avg_price = avg_price
                        existing.avg_price_per_sqm = avg_ppsm
                        existing.min_price = min_price
                        existing.max_price = max_price
                        existing.properties_count = count
                        existing.recorded_at = now
                        if prev_avg and prev_avg > 0:
                            existing.price_change_percent = round(
                                (avg_price - prev_avg) / prev_avg * 100, 2
                            )
                    else:
                        prev = PriceHistory.query.filter_by(
                            complex_id=rc.id,
                            record_type='complex',
                        ).order_by(PriceHistory.year.desc(), PriceHistory.month.desc()).first()

                        change_pct = None
                        if prev and prev.avg_price and prev.avg_price > 0:
                            change_pct = round(
                                (avg_price - prev.avg_price) / prev.avg_price * 100, 2
                            )

                        record = PriceHistory(
                            complex_id=rc.id,
                            record_type='complex',
                            avg_price=avg_price,
                            avg_price_per_sqm=avg_ppsm,
                            min_price=min_price,
                            max_price=max_price,
                            properties_count=count,
                            price_change_percent=change_pct,
                            recorded_at=now,
                            month=month,
                            year=year,
                        )
                        db.session.add(record)

                    saved += 1

                except Exception as e:
                    logger.warning(f"Price snapshot error for complex {rc.id}: {e}")
                    continue

            db.session.commit()
            logger.info(f"✅ Price snapshots: saved={saved}, skipped={skipped}, total_complexes={len(complexes)}")
            return saved

        except Exception as e:
            logger.error(f"❌ Price snapshot job failed: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass
            return 0
