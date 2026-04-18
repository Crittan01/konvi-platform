-- Migración para añadir Costo de Envío a los pedidos

ALTER TABLE public.orders 
ADD COLUMN shipping_cost DECIMAL(10,2) NOT NULL DEFAULT 0;
