import os
import sys
from pathlib import Path

# Add the project directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from app.extensions import db
from sqlalchemy import inspect, text, exc

def migrate_database():
    """Add missing columns to existing tables"""
    try:
        app = create_app()
        
        with app.app_context():
            print("Starting database migration...")
            
            # Get database inspector
            inspector = inspect(db.engine)
            
            # Check and add 'brand' column to products table
            print("Checking products table...")
            products_columns = [col['name'] for col in inspector.get_columns('products')]
            print(f"Existing columns: {products_columns}")
            
            if 'brand' not in products_columns:
                print("Adding 'brand' column to products table...")
                try:
                    db.session.execute(text('ALTER TABLE products ADD COLUMN brand VARCHAR(100)'))
                    db.session.commit()
                    print("✓ 'brand' column added successfully!")
                except exc.OperationalError as e:
                    if "duplicate column name" in str(e) or "already exists" in str(e):
                        print("✓ 'brand' column already exists!")
                        db.session.rollback()
                    else:
                        raise
            else:
                print("✓ 'brand' column already exists!")

            if 'unit_value' not in products_columns:
                print("Adding 'unit_value' column to products table...")
                try:
                    db.session.execute(text('ALTER TABLE products ADD COLUMN unit_value FLOAT NOT NULL DEFAULT 0.0'))
                    db.session.commit()
                    print("✓ 'unit_value' column added successfully!")
                except exc.OperationalError as e:
                    if "duplicate column name" in str(e) or "already exists" in str(e):
                        print("✓ 'unit_value' column already exists!")
                        db.session.rollback()
                    else:
                        raise
            else:
                print("✓ 'unit_value' column already exists!")
            
            # Check if purchases table needs to be created
            print("Checking purchases table...")
            existing_tables = inspector.get_table_names()
            if 'purchases' not in existing_tables:
                print("Creating 'purchases' table...")
                db.create_all()
                print("✓ 'purchases' table created successfully!")
            else:
                print("✓ 'purchases' table already exists!")
            
            print("\n✓ Database migration completed successfully!")
            return True
            
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = migrate_database()
    sys.exit(0 if success else 1)
