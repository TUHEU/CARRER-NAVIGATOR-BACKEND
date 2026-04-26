import unittest
import json
from app import app


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
    
    def test_register_missing_email(self):
        response = self.app.post('/auth/register', 
                                 json={'password': '123456'})
        data = json.loads(response.data)
        self.assertFalse(data['success'])
        self.assertEqual(response.status_code, 400)
    
    def test_login_invalid_credentials(self):
        response = self.app.post('/auth/login',
                                 json={'email': 'wrong@test.com', 
                                       'password': 'wrongpass'})
        data = json.loads(response.data)
        self.assertFalse(data['success'])
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()