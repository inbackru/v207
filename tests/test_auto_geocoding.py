"""
Unit tests for AutoGeocodingService
Тестирование dry-run режима и базового функционала обогащения
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from services.auto_geocoding import AutoGeocodingService, get_auto_geocoding_service
from models import Property


@pytest.fixture
def mock_dadata_client():
    """Mock DaData client для тестов"""
    with patch('services.auto_geocoding.get_dadata_client') as mock:
        client = MagicMock()
        # Успешный ответ DaData
        client.enrich_property_address.return_value = {
            'parsed_city': 'Сочи',
            'parsed_area': 'Центральный район',
            'parsed_settlement': 'Лазаревский',
            'parsed_street': 'Пластунская улица',
            'parsed_house': '104Б',
            'parsed_block': 'к2',
            'parsed_district': 'Центральный район, Лазаревский',
            'latitude': 43.585278,
            'longitude': 39.723098,
            'full_address': 'г Сочи, Пластунская ул, д 104Б к2'
        }
        mock.return_value = client
        yield client


@pytest.fixture
def mock_yandex_service():
    """Mock Yandex geocoding service"""
    with patch('services.auto_geocoding.get_geocoding_service') as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def sample_properties():
    """Создаем тестовые объекты Property"""
    props = []
    for i in range(3):
        prop = Property()
        prop.id = i + 1
        prop.title = f'Test Property {i+1}'
        prop.address = f'Россия, Краснодарский край, Сочи, Тестовая улица, {i+1}'
        prop.latitude = 43.585 + i * 0.001
        prop.longitude = 39.723 + i * 0.001
        prop.parsed_city = None
        prop.parsed_area = None
        props.append(prop)
    return props


class TestAutoGeocodingService:
    """Тесты для AutoGeocodingService"""
    
    def test_dry_run_does_not_commit(self, mock_dadata_client, mock_yandex_service, sample_properties):
        """
        Тест: dry-run режим НЕ должен сохранять изменения в БД
        """
        with patch('app.db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            
            service = AutoGeocodingService()
            service.enable_batch_mode()
            
            # Запускаем с dry_run=True
            stats = service.enrich_batch(sample_properties, batch_size=10, dry_run=True)
            
            # Проверяем что rollback был вызван (dry-run откатывает изменения)
            assert mock_session.rollback.called, "dry-run должен вызвать rollback"
            
            # Проверяем что commit НЕ был вызван
            assert not mock_session.commit.called, "dry-run НЕ должен вызывать commit"
            
            # Проверяем статистику
            assert stats['total'] == 3
            assert stats['enriched'] == 3
            assert stats['errors'] == 0
    
    def test_normal_mode_commits(self, mock_dadata_client, mock_yandex_service, sample_properties):
        """
        Тест: обычный режим ДОЛЖЕН сохранять изменения в БД
        """
        with patch('app.db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            
            service = AutoGeocodingService()
            service.enable_batch_mode()
            
            # Запускаем с dry_run=False
            stats = service.enrich_batch(sample_properties, batch_size=10, dry_run=False)
            
            # Проверяем что commit был вызван
            assert mock_session.commit.called, "normal mode должен вызвать commit"
            
            # Проверяем что rollback НЕ был вызван (только при ошибках)
            # В нормальном режиме rollback вызывается только при исключениях
            
            # Проверяем статистику
            assert stats['total'] == 3
            assert stats['enriched'] == 3
            assert stats['errors'] == 0
    
    def test_enrichment_fills_all_fields(self, mock_dadata_client, mock_yandex_service, sample_properties):
        """
        Тест: проверка что все поля заполняются корректно
        """
        with patch('app.db') as mock_db:
            service = AutoGeocodingService()
            service.enable_batch_mode()
            
            stats = service.enrich_batch(sample_properties, batch_size=10, dry_run=True)
            
            # Проверяем что все объекты обогащены
            for prop in sample_properties:
                assert prop.parsed_city == 'Сочи'
                assert prop.parsed_area == 'Центральный район'
                assert prop.parsed_settlement == 'Лазаревский'
                assert prop.parsed_street == 'Пластунская улица'
                assert prop.parsed_house == '104Б'
                assert prop.parsed_block == 'к2'
                assert prop.parsed_district == 'Центральный район, Лазаревский'
    
    def test_statistics_accuracy(self, mock_dadata_client, mock_yandex_service):
        """
        Тест: проверка точности статистики
        """
        with patch('app.db') as mock_db:
            # Создаем тестовые данные с разными состояниями
            props = []
            
            # 2 объекта для успешного обогащения
            for i in range(2):
                prop = Property()
                prop.id = i + 1
                prop.title = f'Success {i+1}'
                prop.address = f'Тестовый адрес {i+1}'
                prop.parsed_area = None
                props.append(prop)
            
            # 1 объект с ошибкой (нет адреса)
            prop_error = Property()
            prop_error.id = 3
            prop_error.title = 'Error'
            prop_error.address = None  # Нет адреса
            prop_error.parsed_area = None
            props.append(prop_error)
            
            # 1 объект уже обогащен
            prop_skipped = Property()
            prop_skipped.id = 4
            prop_skipped.title = 'Skipped'
            prop_skipped.address = 'Тестовый адрес'
            prop_skipped.parsed_city = 'Сочи'
            prop_skipped.parsed_area = 'Уже обогащен'  # Уже есть данные
            props.append(prop_skipped)
            
            service = AutoGeocodingService()
            service.enable_batch_mode()
            
            stats = service.enrich_batch(props, batch_size=10, dry_run=True)
            
            # Проверяем статистику
            assert stats['total'] == 4, "Всего должно быть 4 объекта"
            assert stats['enriched'] == 2, "Должно быть обогащено 2 объекта"
            assert stats['skipped'] == 2, "Должно быть пропущено 2 объекта (1 без адреса, 1 уже обогащен)"
    
    def test_batch_mode_flag(self, mock_dadata_client, mock_yandex_service):
        """
        Тест: проверка работы batch_mode флага
        """
        service = AutoGeocodingService()
        
        # По умолчанию batch_mode выключен
        assert service.batch_mode == False
        
        # Включаем batch_mode
        service.enable_batch_mode()
        assert service.batch_mode == True
        
        # Выключаем batch_mode
        service.disable_batch_mode()
        assert service.batch_mode == False
    
    def test_singleton_service(self):
        """
        Тест: get_auto_geocoding_service возвращает singleton
        """
        service1 = get_auto_geocoding_service()
        service2 = get_auto_geocoding_service()
        
        # Должен быть один и тот же объект
        assert service1 is service2


class TestDryRunIntegration:
    """Интеграционные тесты для dry-run режима"""
    
    def test_dry_run_leaves_database_unchanged(self, mock_dadata_client, mock_yandex_service):
        """
        Интеграционный тест: dry-run должен оставить БД без изменений
        """
        with patch('app.db') as mock_db:
            # Имитируем начальное состояние БД
            initial_state = {'parsed_area': None, 'parsed_city': None}
            
            prop = Property()
            prop.address = 'Тестовый адрес'
            prop.parsed_area = initial_state['parsed_area']
            prop.parsed_city = initial_state['parsed_city']
            
            service = AutoGeocodingService()
            service.enable_batch_mode()
            
            # Запускаем dry-run
            stats = service.enrich_batch([prop], batch_size=1, dry_run=True)
            
            # Проверяем что rollback был вызван
            assert mock_db.session.rollback.called
            
            # В реальной БД данные должны остаться без изменений
            # (rollback откатывает все изменения)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
