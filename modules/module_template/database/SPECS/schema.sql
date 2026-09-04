-- GENERATED — DO NOT EDIT, AND NOTHING APPLIES THIS FILE.
--
-- The schema of a fresh installation: the Alembic migrations applied to an empty
-- database and dumped, for reading and review. Alembic applies the schema (see the
-- module's migrations job); this file is a derived artifact. Editing it changes
-- nothing, and re-adding DDL that Alembic does not know about is how deployed
-- databases drifted from the repository before.
--
-- Regenerate:  scripts/dev/schema.sh schema-sql module_template



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: -

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


SET default_tablespace = '';

SET default_table_access_method = heap;

-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


-- Name: module_bootstrap_execution; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.module_bootstrap_execution (
    script_key text NOT NULL,
    executed_at timestamp with time zone DEFAULT now() NOT NULL
);


-- Name: module_runtime_meta; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.module_runtime_meta (
    key text NOT NULL,
    value timestamp with time zone NOT NULL
);


-- Name: template_items; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.template_items (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text
);

ALTER TABLE ONLY public.template_items FORCE ROW LEVEL SECURITY;


-- Name: template_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.template_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


-- Name: template_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.template_items_id_seq OWNED BY public.template_items.id;


-- Name: template_items_version; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.template_items_version (
    id integer NOT NULL,
    tenant_id integer,
    name character varying(255),
    description text,
    transaction_id bigint NOT NULL,
    end_transaction_id bigint,
    operation_type smallint NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.template_items_version FORCE ROW LEVEL SECURITY;


-- Name: transaction; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.transaction (
    id bigint NOT NULL,
    remote_addr character varying(50),
    issued_at timestamp with time zone NOT NULL
);


-- Name: transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.transaction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


-- Name: transaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.transaction_id_seq OWNED BY public.transaction.id;


-- Name: transaction_meta; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.transaction_meta (
    transaction_id bigint NOT NULL,
    key character varying(255) NOT NULL,
    value text
);


-- Name: template_items id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.template_items ALTER COLUMN id SET DEFAULT nextval('public.template_items_id_seq'::regclass);


-- Name: transaction id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.transaction ALTER COLUMN id SET DEFAULT nextval('public.transaction_id_seq'::regclass);


-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


-- Name: module_bootstrap_execution module_bootstrap_execution_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.module_bootstrap_execution
    ADD CONSTRAINT module_bootstrap_execution_pkey PRIMARY KEY (script_key);


-- Name: module_runtime_meta module_runtime_meta_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.module_runtime_meta
    ADD CONSTRAINT module_runtime_meta_pkey PRIMARY KEY (key);


-- Name: template_items template_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.template_items
    ADD CONSTRAINT template_items_pkey PRIMARY KEY (id);


-- Name: template_items_version template_items_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.template_items_version
    ADD CONSTRAINT template_items_version_pkey PRIMARY KEY (id, transaction_id, issued_at);


-- Name: transaction_meta transaction_meta_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.transaction_meta
    ADD CONSTRAINT transaction_meta_pkey PRIMARY KEY (transaction_id, key);


-- Name: transaction transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_pkey PRIMARY KEY (id, issued_at);


-- Name: idx_template_items_description_trgm; Type: INDEX; Schema: public; Owner: -

CREATE INDEX idx_template_items_description_trgm ON public.template_items USING gin (description public.gin_trgm_ops);


-- Name: idx_template_items_name; Type: INDEX; Schema: public; Owner: -

CREATE INDEX idx_template_items_name ON public.template_items USING btree (name);


-- Name: idx_template_items_name_trgm; Type: INDEX; Schema: public; Owner: -

CREATE INDEX idx_template_items_name_trgm ON public.template_items USING gin (name public.gin_trgm_ops);


-- Name: idx_template_items_tenant_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX idx_template_items_tenant_id ON public.template_items USING btree (tenant_id, id);


-- Name: idx_template_items_tenant_name; Type: INDEX; Schema: public; Owner: -

CREATE INDEX idx_template_items_tenant_name ON public.template_items USING btree (tenant_id, name);


-- Name: ix_template_items_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_id ON public.template_items USING btree (id);


-- Name: ix_template_items_tenant_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_tenant_id ON public.template_items USING btree (tenant_id);


-- Name: ix_template_items_version_end_transaction_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_version_end_transaction_id ON public.template_items_version USING btree (end_transaction_id);


-- Name: ix_template_items_version_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_version_id ON public.template_items_version USING btree (id);


-- Name: ix_template_items_version_operation_type; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_version_operation_type ON public.template_items_version USING btree (operation_type);


-- Name: ix_template_items_version_tenant_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_version_tenant_id ON public.template_items_version USING btree (tenant_id);


-- Name: ix_template_items_version_transaction_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_template_items_version_transaction_id ON public.template_items_version USING btree (transaction_id);


-- Name: template_items_version_issued_at_idx; Type: INDEX; Schema: public; Owner: -

CREATE INDEX template_items_version_issued_at_idx ON public.template_items_version USING btree (issued_at DESC);


-- Name: transaction_issued_at_idx; Type: INDEX; Schema: public; Owner: -

CREATE INDEX transaction_issued_at_idx ON public.transaction USING btree (issued_at DESC);


-- Name: template_items_version ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.template_items_version FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


-- Name: transaction ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.transaction FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


-- Name: template_items; Type: ROW SECURITY; Schema: public; Owner: -

ALTER TABLE public.template_items ENABLE ROW LEVEL SECURITY;

-- Name: template_items_version; Type: ROW SECURITY; Schema: public; Owner: -

ALTER TABLE public.template_items_version ENABLE ROW LEVEL SECURITY;

-- Name: template_items tenant_cross_read; Type: POLICY; Schema: public; Owner: -

CREATE POLICY tenant_cross_read ON public.template_items FOR SELECT USING ((current_setting('app.cross_tenant_read'::text, true) = 'on'::text));


-- Name: template_items_version tenant_cross_read; Type: POLICY; Schema: public; Owner: -

CREATE POLICY tenant_cross_read ON public.template_items_version FOR SELECT USING ((current_setting('app.cross_tenant_read'::text, true) = 'on'::text));


-- Name: template_items tenant_isolation; Type: POLICY; Schema: public; Owner: -

CREATE POLICY tenant_isolation ON public.template_items USING ((tenant_id = ANY ((string_to_array(current_setting('app.tenant_ids'::text, true), ','::text))::integer[])));


-- Name: template_items_version tenant_isolation; Type: POLICY; Schema: public; Owner: -

CREATE POLICY tenant_isolation ON public.template_items_version USING ((tenant_id = ANY ((string_to_array(current_setting('app.tenant_ids'::text, true), ','::text))::integer[])));



