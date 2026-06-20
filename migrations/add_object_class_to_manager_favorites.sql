-- Migration: Add object_class_display_name to manager_favorite_complexes
-- Description: Adds housing class field for residential complexes in manager favorites
-- Date: 2025-11-11
-- Author: System

-- Add object_class_display_name column to store housing class (эконом, комфорт, бизнес, etc.)
ALTER TABLE manager_favorite_complexes 
ADD COLUMN IF NOT EXISTS object_class_display_name VARCHAR(100);

-- Update existing records with data from residential_complexes table where possible
UPDATE manager_favorite_complexes mfc
SET object_class_display_name = rc.object_class_display_name
FROM residential_complexes rc
WHERE mfc.complex_id IS NOT NULL 
  AND mfc.complex_id::INTEGER = rc.id
  AND rc.object_class_display_name IS NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN manager_favorite_complexes.object_class_display_name IS 
'Класс жилья ЖК (эконом, комфорт, бизнес и т.д.)';
