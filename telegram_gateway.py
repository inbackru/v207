import os
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TelegramGatewayService:
    BASE_URL = "https://gatewayapi.telegram.org/"

    def __init__(self):
        self.token = os.environ.get('TELEGRAM_GATEWAY_TOKEN')
        if not self.token:
            logger.warning("TELEGRAM_GATEWAY_TOKEN not found in environment variables")

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    def _format_phone(self, phone: str) -> Optional[str]:
        phone_clean = ''.join(filter(str.isdigit, phone))
        if phone_clean.startswith('8') and len(phone_clean) == 11:
            phone_clean = '7' + phone_clean[1:]
        elif phone_clean.startswith('9') and len(phone_clean) == 10:
            phone_clean = '7' + phone_clean
        if len(phone_clean) != 11 or not phone_clean.startswith('7'):
            logger.warning(f"Invalid phone format for Telegram Gateway: length={len(phone_clean)}")
            return None
        return f'+{phone_clean}'

    def check_send_ability(self, phone: str) -> Dict[str, Any]:
        if not self.is_configured:
            return {'ok': False, 'error': 'NOT_CONFIGURED'}

        phone_formatted = self._format_phone(phone)
        if not phone_formatted:
            return {'ok': False, 'error': 'INVALID_PHONE'}

        try:
            response = requests.post(
                self.BASE_URL + 'checkSendAbility',
                headers=self._headers(),
                json={'phone_number': phone_formatted},
                timeout=10
            )

            if response.headers.get('content-type', '').startswith('application/json'):
                data = response.json()
            else:
                logger.error(f"Telegram Gateway non-JSON response: {response.status_code}")
                return {'ok': False, 'error': 'NON_JSON_RESPONSE'}

            logger.info(f"Telegram Gateway checkSendAbility for {phone_formatted[:5]}****: {data.get('ok')}")
            return data

        except Exception as e:
            logger.error(f"Telegram Gateway checkSendAbility error: {e}")
            return {'ok': False, 'error': str(e)}

    def send_verification_message(self, phone: str, code: str, ttl: int = 120) -> Dict[str, Any]:
        if not self.is_configured:
            logger.warning("Telegram Gateway not configured, skipping")
            return {
                'success': False,
                'message': 'Telegram Gateway не настроен',
                'channel': 'telegram_gateway'
            }

        phone_formatted = self._format_phone(phone)
        if not phone_formatted:
            return {
                'success': False,
                'message': 'Неверный формат номера',
                'channel': 'telegram_gateway'
            }

        payload = {
            'phone_number': phone_formatted,
            'code': code,
            'code_length': len(code),
            'ttl': max(30, min(ttl, 3600)),
        }

        try:
            logger.info(f"Sending verification via Telegram Gateway to {phone_formatted[:5]}****")

            response = requests.post(
                self.BASE_URL + 'sendVerificationMessage',
                headers=self._headers(),
                json=payload,
                timeout=15
            )

            if not response.headers.get('content-type', '').startswith('application/json'):
                logger.error(f"Telegram Gateway non-JSON response: {response.status_code}")
                return {
                    'success': False,
                    'message': 'Telegram Gateway: неверный ответ',
                    'channel': 'telegram_gateway'
                }

            data = response.json()
            logger.info(f"Telegram Gateway response: ok={data.get('ok')}, status_code={response.status_code}")

            if data.get('ok'):
                result_data = data.get('result', {})
                request_id = result_data.get('request_id', '')
                delivery = result_data.get('delivery_status', {})
                status = delivery.get('status', 'unknown')

                logger.info(f"Telegram Gateway sent successfully. request_id={request_id}, status={status}")

                return {
                    'success': True,
                    'message': 'Код отправлен через Telegram',
                    'channel': 'telegram_gateway',
                    'request_id': request_id,
                    'delivery_status': status
                }
            else:
                error = data.get('error', 'Unknown error')
                logger.warning(f"Telegram Gateway failed: {error}")
                return {
                    'success': False,
                    'message': f'Telegram Gateway ошибка: {error}',
                    'channel': 'telegram_gateway',
                    'error': error
                }

        except requests.exceptions.Timeout:
            logger.error("Telegram Gateway timeout")
            return {
                'success': False,
                'message': 'Telegram Gateway: таймаут',
                'channel': 'telegram_gateway'
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram Gateway request error: {e}")
            return {
                'success': False,
                'message': f'Telegram Gateway: ошибка соединения',
                'channel': 'telegram_gateway'
            }
        except Exception as e:
            logger.error(f"Telegram Gateway unexpected error: {e}")
            return {
                'success': False,
                'message': f'Telegram Gateway: неожиданная ошибка',
                'channel': 'telegram_gateway'
            }

    def check_verification_status(self, request_id: str, code: str) -> Dict[str, Any]:
        if not self.is_configured:
            return {'ok': False, 'error': 'NOT_CONFIGURED'}

        try:
            response = requests.post(
                self.BASE_URL + 'checkVerificationStatus',
                headers=self._headers(),
                json={
                    'request_id': request_id,
                    'code': code
                },
                timeout=10
            )

            data = response.json()
            logger.info(f"Telegram Gateway checkVerificationStatus: {data.get('ok')}")
            return data

        except Exception as e:
            logger.error(f"Telegram Gateway checkVerificationStatus error: {e}")
            return {'ok': False, 'error': str(e)}

    def revoke_verification(self, request_id: str) -> Dict[str, Any]:
        if not self.is_configured:
            return {'ok': False, 'error': 'NOT_CONFIGURED'}

        try:
            response = requests.post(
                self.BASE_URL + 'revokeVerificationMessage',
                headers=self._headers(),
                json={'request_id': request_id},
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Telegram Gateway revoke error: {e}")
            return {'ok': False, 'error': str(e)}


tg_gateway = TelegramGatewayService()
