-- Supabase: SQL Editor > paste all > Run.   (The app also creates/updates these tables by itself on start-up,
-- so this file is optional. Its main job is the Row Level Security part at the bottom.)
create table if not exists app_users (
  id serial primary key, email varchar(255) unique not null, password_hash varchar(255) not null,
  role varchar(20) not null default 'user', failed_attempts int not null default 0,
  locked boolean not null default false, created_at timestamp default now(),
  totp_secret varchar(64), totp_enabled boolean not null default false);
create table if not exists app_settings (key varchar(50) primary key, value varchar(100) not null);
create table if not exists app_quotes (
  id serial primary key, invoice_no varchar(60) not null, invoice_date varchar(30) not null,
  distributor varchar(120) default '', customer_name varchar(200) not null, customer_address text default '',
  margin double precision, fx_rate double precision, vat_rate double precision, note text default '',
  show_rate boolean default true, items_json text, total_usd double precision default 0,
  total_ngn double precision default 0, created_by varchar(255), created_at timestamp default now(),
  source_currency varchar(3) default 'USD', quote_currency varchar(3) default 'NGN', meta_json text default '{}');
create index if not exists ix_app_quotes_invoice_no on app_quotes(invoice_no);
create table if not exists app_audit (
  id serial primary key, ts timestamp default now(), actor varchar(255) default '', action varchar(60) not null,
  detail varchar(500) default '', ip varchar(64) default '');
create index if not exists ix_app_audit_ts on app_audit(ts);
create index if not exists ix_app_audit_action on app_audit(action);

-- IMPORTANT on Supabase: block the public REST API from these tables. Our backend connects directly with the
-- database password, so with RLS ON and NO policies, the public (anon) key can read nothing.
alter table app_users enable row level security;
alter table app_settings enable row level security;
alter table app_quotes enable row level security;
alter table app_audit enable row level security;
