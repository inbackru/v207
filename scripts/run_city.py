#!/usr/bin/env python3
"""
Единая точка входа для обогащения любого города из CIAN.

Использование:
  python3 scripts/run_city.py --city 1              # Краснодар, полный прогон
  python3 scripts/run_city.py --city 2              # Сочи, полный прогон
  python3 scripts/run_city.py --city 1 --mode prices  # только цены (~5 мин)
  python3 scripts/run_city.py --city 2 --mode prices
  python3 scripts/run_city.py --city 1 --reset      # сбросить кэш и запустить заново
  python3 scripts/run_city.py --list                # показать все доступные города

Добавить новый город: просто допишите запись в scripts/city_config.json
и убедитесь что city_id совпадает с residential_complexes.city_id в БД.
"""
import os
import sys
import json
import argparse
import subprocess

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_city_config() -> dict:
    cfg_path = os.path.join(_SCRIPTS_DIR, 'city_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f'❌ city_config.json не найден: {cfg_path}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'❌ Ошибка чтения city_config.json: {e}')
        sys.exit(1)


def list_cities(configs: dict):
    print('┌─────────────────────────────────────────────────────┐')
    print('│  Доступные города для обогащения                    │')
    print('├───┬───────────────────┬────────────┬────────────────┤')
    print('│ # │ Название          │ CIAN RegID │ Страниц макс   │')
    print('├───┼───────────────────┼────────────┼────────────────┤')
    for cid, cfg in sorted(configs.items(), key=lambda x: int(x[0])):
        print(f'│{int(cid):2d} │ {cfg["name"]:<17} │ {cfg["cian_region_id"]:>10} │ {cfg.get("total_pages", "—"):>14} │')
    print('└───┴───────────────────┴────────────┴────────────────┘')
    print()
    print('Команды:')
    print('  Полный сбор:   python3 scripts/run_city.py --city N')
    print('  Только цены:   python3 scripts/run_city.py --city N --mode prices')
    print('  Сброс кэша:    python3 scripts/run_city.py --city N --reset')
    print('  Обогащение ЖК: python3 scripts/fix_jk_bulk.py --city N')


def reset_cache(city_id: int):
    """Удаляет кэш-файл для указанного города."""
    cache_file = os.path.join(_SCRIPTS_DIR, f'.enrich_cache_city{city_id}.json')
    if os.path.exists(cache_file):
        os.remove(cache_file)
        print(f'🗑️  Кэш города {city_id} удалён: {os.path.basename(cache_file)}')
    else:
        print(f'ℹ️  Кэш города {city_id} не найден — сбрасывать нечего')


def main():
    ap = argparse.ArgumentParser(
        description='Запуск обогащения CIAN для выбранного города',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('--city', type=int, default=None,
                    help='ID города (1=Краснодар, 2=Сочи, …)')
    ap.add_argument('--mode', choices=['full', 'prices'], default='full',
                    help='full=полный прогон, prices=только цены (~5 мин)')
    ap.add_argument('--list', action='store_true',
                    help='Показать список доступных городов и выйти')
    ap.add_argument('--reset', action='store_true',
                    help='Сбросить кэш перед запуском (принудительный полный сбор с ЦИАН)')
    args = ap.parse_args()

    configs = load_city_config()

    if args.list:
        list_cities(configs)
        return

    if args.city is None:
        print('❌ Укажите --city N (или --list чтобы увидеть доступные города)')
        ap.print_help()
        sys.exit(1)

    city_key = str(args.city)
    if city_key not in configs:
        print(f'❌ Город с ID={args.city} не найден в city_config.json.')
        print()
        list_cities(configs)
        sys.exit(1)

    cfg = configs[city_key]
    city_name = cfg['name']
    region_id = cfg['cian_region_id']
    total_pages = cfg.get('total_pages', 54)

    if args.reset:
        reset_cache(args.city)

    mode_label = 'Только цены (~5 мин)' if args.mode == 'prices' else 'Полный прогон'
    print('=' * 62)
    print(f'🏙️  Город:    {city_name} (city_id={args.city})')
    print(f'🗺️  CIAN:     region_id={region_id}  | страниц≤{total_pages}')
    print(f'⚙️  Режим:    {mode_label}')
    if args.reset:
        print(f'🔄  Кэш:     сброшен — полный сбор с нуля')
    print('=' * 62)

    env = os.environ.copy()
    env['ENRICH_CITY_ID']     = str(args.city)
    env['ENRICH_REGION_ID']   = str(region_id)
    env['ENRICH_TOTAL_PAGES'] = str(total_pages)
    env['ENRICH_MODE']        = args.mode
    env['ENRICH_LAT_MIN'] = str(cfg.get('lat_min', 40.0))
    env['ENRICH_LAT_MAX'] = str(cfg.get('lat_max', 80.0))
    env['ENRICH_LON_MIN'] = str(cfg.get('lon_min', 19.0))
    env['ENRICH_LON_MAX'] = str(cfg.get('lon_max', 190.0))

    enrich_script = os.path.join(_SCRIPTS_DIR, 'enrich_complexes.py')
    result = subprocess.run(
        [sys.executable, '-u', enrich_script],
        env=env,
    )
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
