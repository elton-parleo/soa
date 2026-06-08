import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from soa_shared.database import session_factory
from soa_shared.models.soa_models import SoaEntity

ENTITIES = [
    {
        'name': 'Quip',
        'slug': 'quip',
        'entity_type': 'brand',
        'category': 'oral care',
        'website_url': 'https://www.getquip.com',
        'aliases': ['quip toothbrush'],
        'merchant_id': None,
    },
    {
        'name': 'AquaSonic',
        'slug': 'aquasonic',
        'entity_type': 'brand',
        'category': 'oral care',
        'website_url': 'https://www.aquasonicusa.com',
        'aliases': ['Aqua Sonic'],
        'merchant_id': None,
    },
    {
        'name': 'Burst',
        'slug': 'burst',
        'entity_type': 'brand',
        'category': 'oral care',
        'website_url': 'https://www.burstoralcare.com',
        'aliases': ['BURST'],
        'merchant_id': None,
    },
]


def seed():
    with session_factory() as session:
        for e in ENTITIES:
            exists = session.query(SoaEntity)\
                .filter_by(slug=e['slug']).first()
            if exists:
                print(f'Exists:  {e["slug"]}')
            else:
                session.add(SoaEntity(**e))
                print(f'Added:   {e["slug"]}')
        session.commit()
    print('Done')


if __name__ == '__main__':
    seed()
