-- Esquema para Supabase (PostgreSQL). Una fila por lead ORIGINAL; la fusión se expresa con duplicado_de.
create table if not exists public.leads (
  id               text primary key,
  recibido_en      timestamptz not null default now(),
  fecha_origen     date,
  nombre           text,
  empresa          text,
  email            text check (email is null or email ~ '^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$'),
  email_alterno    text,
  telefono         text check (telefono is null or telefono ~ '^\+52[2-9][0-9]{9}$'),
  segmento         text,
  num_empleados    integer check (num_empleados is null or num_empleados > 0),
  empleados_fuente text check (empleados_fuente in ('declarado','mensaje') or empleados_fuente is null),
  ciudad           text,
  fuente           text,
  mensaje          text,
  duplicado_de     text references public.leads(id),
  calificacion     text check (calificacion in ('A','B','C','Descartado')),
  razon            text,
  siguiente_accion text,
  requiere_revision boolean not null default false,
  motivo_revision  text,
  prioridad        integer,
  revisado_por     text,            -- quién validó (Christian)
  revisado_en      timestamptz,
  estado_contacto  text not null default 'pendiente_validacion'
                   check (estado_contacto in ('pendiente_validacion','validado','contactado','descartado'))
);

create index if not exists leads_telefono_idx on public.leads (telefono) where telefono is not null;
create index if not exists leads_email_idx    on public.leads (email)    where email is not null;
create index if not exists leads_cola_idx     on public.leads (calificacion, prioridad) where duplicado_de is null;

-- Nadie contacta a un lead sin validación de Christian.
create or replace view public.cola_para_christian as
  select * from public.leads
  where duplicado_de is null and calificacion <> 'Descartado' and estado_contacto = 'pendiente_validacion'
  order by prioridad;

-- Seguridad: el rol anónimo no lee ni escribe; el webhook usa la service key desde el servidor (nunca en el repo).
alter table public.leads enable row level security;
