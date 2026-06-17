import streamlit as st
import pandas as pd
import json
import os
import re
import streamlit.components.v1 as components
from supabase import create_client, Client

st.set_page_config(page_title="OPTIALU", layout="wide")

# ==========================================
# CONNEXION SUPABASE SAAS
# ==========================================
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["anon_key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    st.sidebar.success("🟢 Connecté à Supabase !")
except Exception as e:
    st.sidebar.error("🔴 Erreur de configuration Supabase. Vérifiez les secrets.")

# ==========================================
# 🔐 GESTION DE L'AUTHENTIFICATION (MULTI-TENANT)
# ==========================================
for key in ["user", "access_token", "refresh_token", "entreprise_id", "user_nom", "nom_entreprise", "gammes_autorisees"]:
    if key not in st.session_state:
        st.session_state[key] = None if key != "gammes_autorisees" else []

def fetch_entreprise_info(ent_id):
    """Fonction utilitaire pour récupérer les infos de l'entreprise et ses gammes"""
    try:
        ent_res = supabase.table("entreprises").select("nom_entreprise, gammes_autorisees").eq("id", ent_id).execute()
        if ent_res.data:
            nom = ent_res.data[0].get("nom_entreprise", "Inconnue")
            gammes_brutes = ent_res.data[0].get("gammes_autorisees", "[]")
            
            if isinstance(gammes_brutes, str):
                try:
                    gammes = json.loads(gammes_brutes)
                except:
                    gammes = []
            else:
                gammes = gammes_brutes if gammes_brutes else []
            return nom, gammes
    except:
        pass
    return "Inconnue", []

# On rappelle à Supabase qui est connecté à chaque rechargement de page
if st.session_state.access_token and st.session_state.refresh_token:
    try:
        supabase.auth.set_session(st.session_state.access_token, st.session_state.refresh_token)
        
        # Sécurité : Si on perd les infos en mémoire, on les récupère
        if st.session_state.entreprise_id and (not st.session_state.get('user_nom') or not st.session_state.get('nom_entreprise')):
            user_id = st.session_state.user.id if st.session_state.user else None
            if user_id:
                profile_res = supabase.table("profiles").select("nom").eq("id", user_id).execute()
                if profile_res.data:
                    st.session_state.user_nom = profile_res.data[0].get("nom", "Utilisateur")
            
            nom_ent, gammes = fetch_entreprise_info(st.session_state.entreprise_id)
            st.session_state.nom_entreprise = nom_ent
            st.session_state.gammes_autorisees = gammes
    except:
        st.session_state.user = None 

def logout():
    supabase.auth.sign_out()
    for key in ["user", "access_token", "refresh_token", "entreprise_id", "user_nom", "nom_entreprise"]:
        st.session_state[key] = None
    st.session_state.gammes_autorisees = []
    st.cache_data.clear() 
    st.rerun()

# Écran de connexion si non connecté
if st.session_state.user is None:
    st.markdown('<div class="main-title">🔐 Connexion OPTIALU</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.info("Veuillez vous connecter pour accéder à l'espace de votre entreprise.")
        email = st.text_input("Adresse E-mail")
        password = st.text_input("Mot de passe", type="password")
        
        if st.button("Se connecter", type="primary", use_container_width=True):
            try:
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                
                st.session_state.user = response.user
                st.session_state.access_token = response.session.access_token
                st.session_state.refresh_token = response.session.refresh_token
                
                # Récupération du profil
                user_id = response.user.id
                profile_res = supabase.table("profiles").select("entreprise_id", "nom").eq("id", user_id).execute()
                
                if profile_res.data:
                    st.session_state.entreprise_id = profile_res.data[0]["entreprise_id"]
                    st.session_state.user_nom = profile_res.data[0].get("nom", "Utilisateur")
                    
                    nom_ent, gammes = fetch_entreprise_info(st.session_state.entreprise_id)
                    st.session_state.nom_entreprise = nom_ent
                    st.session_state.gammes_autorisees = gammes
                    
                    st.cache_data.clear() 
                    st.rerun()
                else:
                    st.error("🔴 Votre compte n'est lié à aucune entreprise. Contactez l'administrateur.")
                    supabase.auth.sign_out() 
                    st.session_state.user = None
            except Exception as e:
                st.error("🔴 Identifiants incorrects. Veuillez réessayer.")
                
    st.stop() 

# --- Utilisateur authentifié & lié à une entreprise ---

st.markdown('<div class="main-title">OPTIALU</div>', unsafe_allow_html=True)

nom_ent_affiche = st.session_state.get('nom_entreprise') or "Inconnue"
nom_usr_affiche = st.session_state.get('user_nom') or "Utilisateur"

st.markdown(
    f"""
    <div style="background-color: #f0f2f6; padding: 12px 20px; border-radius: 8px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; border-left: 5px solid #1E3A8A;">
        <span style="font-size: 16px; color: #333;">🏢 Entreprise : <strong>{nom_ent_affiche}</strong></span>
        <span style="font-size: 16px; color: #333;">👤 Utilisateur : <strong>{nom_usr_affiche}</strong></span>
    </div>
    """, 
    unsafe_allow_html=True
)

st.sidebar.button("🚪 Se déconnecter", on_click=logout, use_container_width=True)
st.sidebar.markdown("---")

# ==========================================
# GESTION DES DONNÉES & CATALOGUE (FILTRÉ)
# ==========================================
@st.cache_data(ttl=3600) 
def load_app_library(entreprise_id, gammes_autorisees_liste):
    try:
        if not gammes_autorisees_liste:
            return []
            
        # Filtrage Supabase par la colonne 'gamme'
        response = supabase.table("bibliotheque_gammes").select("*").in_("gamme", gammes_autorisees_liste).execute()
        data_sql = response.data
        
        legacy_data = []
        for item in data_sql:
            legacy_data.append({
                "Gamme": item.get("gamme", ""),
                "Type Ouvrage": item.get("type_ouvrage", ""),
                "Composant": item.get("composant", ""),
                "Ref": item.get("ref", ""),
                "Formule Long": item.get("formule_long", ""),
                "Qté": item.get("qte", 1),
                "Unité": item.get("unite", ""),
                "Type": item.get("type_article", ""),
                "PU": item.get("pu", 0),
                "Série": item.get("serie", "")
            })
        return legacy_data
    except Exception as e:
        st.error(f"⚠️ Erreur de chargement du catalogue depuis le Cloud : {e}")
        return []

mes_gammes = st.session_state.get("gammes_autorisees", [])
mon_entreprise_id = st.session_state.get("entreprise_id", "inconnu")

BIBLIOTHEQUE = load_app_library(mon_entreprise_id, mes_gammes)
PALETTE_COULEURS = ["#1E40AF", "#10B981", "#D97706", "#DC2626", "#7C3AED", "#0891B2", "#EC4899"]

# Génération des listes déroulantes dynamiques depuis la bibliothèque filtrée
choix_gammes_dynamiques = sorted(list(set([str(x.get("Gamme", "")).strip() for x in BIBLIOTHEQUE if str(x.get("Gamme", "")).strip() != ""])))
choix_series_dynamiques = sorted(list(set([str(x.get("Série", "")).strip() for x in BIBLIOTHEQUE if str(x.get("Série", "")).strip() != ""])))
choix_types_dynamiques = sorted(list(set([str(x.get("Type Ouvrage", "")).strip() for x in BIBLIOTHEQUE if str(x.get("Type Ouvrage", "")).strip() != ""])))

# Fallbacks si la bibliothèque est vide
if not choix_gammes_dynamiques: choix_gammes_dynamiques = ["-"]
if not choix_series_dynamiques: choix_series_dynamiques = ["-"]
if not choix_types_dynamiques: choix_types_dynamiques = ["-"]

def get_default_df():
    return pd.DataFrame([{
        "Repère": "F1" if choix_types_dynamiques[0].upper().startswith("F") else "O1", 
        "Gamme": choix_gammes_dynamiques[0],
        "Série": choix_series_dynamiques[0],
        "Ouvrage": choix_types_dynamiques[0], 
        "Largeur (L)": 1000.0, 
        "Hauteur (H)": 1000.0, 
        "Qté": 1, 
        "Volet Roulant": "non", 
        "H Caisson": 0.0, 
        "Vitrage": ""
    }])

if "chassis_rows_v27" not in st.session_state:
    st.session_state.chassis_rows_v27 = get_default_df()
if "current_project_name" not in st.session_state:
    st.session_state.current_project_name = "Nouveau Projet (Non Sauvegardé)"
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None

# --- Injection CSS ---
st.markdown("""
    <style>
    .main-title { font-size:24px !important; font-weight: bold; color: #1E3A8A; margin-bottom: 20px; text-align: center; border-bottom: 3px solid #1E3A8A; padding-bottom: 10px;}
    .projet-title { font-size: 24px; font-weight: bold; color: #DC2626; text-align: center; margin-bottom: 20px; text-transform: uppercase;}
    .section-header { font-size:18px !important; font-weight: bold; color: #0F172A; margin-top: 20px; margin-bottom: 10px; padding: 6px 0;}
    .excel-head-yellow { background-color: #FEF08A; color: #713F12; padding: 8px; font-weight: bold; border-radius: 4px; margin-bottom: 10px; font-size: 15px;}
    .excel-head-blue { background-color: #DBEAFE; color: #1E40AF; padding: 8px; font-weight: bold; border-radius: 4px; margin-bottom: 10px; font-size: 15px; text-transform: uppercase;}
    .excel-head-green { background-color: #DCFCE7; color: #14532D; padding: 8px; font-weight: bold; border-radius: 4px; margin-bottom: 10px; font-size: 15px;}
    .excel-head-gray { background-color: #F3F4F6; color: #374151; padding: 8px; font-weight: bold; border-radius: 4px; margin-bottom: 10px; font-size: 15px; border: 1px solid #D1D5DB;}
    .badge-serie { background-color: #4B5563; color: white; font-weight: bold; padding: 8px 12px; border-radius: 4px 4px 0 0; display: inline-block; margin-top: 20px; font-size: 14px; -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;}
    .print-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px; font-family: sans-serif; }
    .print-table th, .print-table td { border: 1px solid #9CA3AF; padding: 6px; text-align: left; vertical-align: middle; }
    .print-table th { background-color: #F3F4F6; color: #111827; font-weight: bold; -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;}
    .print-table th.yellow-head { background-color: #FEF08A !important; color: #111827 !important; text-align: center; vertical-align: bottom; }
    .print-table td.center-text { text-align: center; font-weight: 500; }
    .bar-container { display: flex; background-color: #F3F4F6; border: 1px solid #4B5563; border-radius: 2px; height: 32px; width: 100%; overflow: hidden; box-sizing: border-box; margin: 0;}
    .bar-segment { display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 12px; height: 100%; border-right: 1px solid #FFFFFF !important; box-sizing: border-box; white-space: nowrap; overflow: hidden; -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;}
    .bar-chute { display: flex; align-items: center; justify-content: center; background-color: #E5E7EB; color: #6B7280; font-size: 11px; height: 100%; box-sizing: border-box; flex-grow: 1; -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important;}
    .block-spacer { margin-top: 40px; }
    @media print {
        header, [data-testid="stSidebar"], [role="tablist"], [data-testid="stDataEditor"], iframe, .main-title { display: none !important; }
        .no-print { display: none !important; }
        @page { size: A4; margin: 0mm; }
        .main .block-container { max-width: 100% !important; padding: 10mm !important; margin: 0 !important; }
    }
    </style>
""", unsafe_allow_html=True)

def clean_string(s):
    if not s: return ""
    return re.sub(r'\s+', '', str(s)).upper().strip()

# ==========================================
# 📁 GESTION SÉCURISÉE DES PROJETS (SAAS)
# ==========================================
st.sidebar.header("📁 Gestion des Projets")

def fetch_project_list():
    try:
        response = supabase.table("projets").select("id, nom_projet").eq("entreprise_id", st.session_state.entreprise_id).execute()
        return response.data  
    except:
        return []

st.session_state.liste_projets_sauvegardes = fetch_project_list()
projets_existants = st.session_state.liste_projets_sauvegardes

# --- Créer un nouveau projet ---
nouveau_projet = st.sidebar.text_input("➕ Créer un nouveau projet :", placeholder="Ex: Villa Dupont")
if st.sidebar.button("Créer ce projet", use_container_width=True):
    if nouveau_projet:
        data_json = json.loads(st.session_state.chassis_rows_v27.to_json(orient="records", force_ascii=False))
        try:
            response = supabase.table("projets").insert({
                "user_id": st.session_state.user.id,
                "entreprise_id": st.session_state.entreprise_id, 
                "nom_projet": nouveau_projet,
                "donnees": data_json
            }).execute()
            
            if response.data:
                st.session_state.current_project_id = response.data[0]["id"]
                st.session_state.current_project_name = nouveau_projet
                st.session_state.chassis_rows_v27 = get_default_df()
                st.session_state.liste_projets_sauvegardes = fetch_project_list()
                st.sidebar.success(f"Projet '{nouveau_projet}' créé !")
                st.rerun()
        except Exception as e:
            st.sidebar.error(f"Erreur de création : {e}")

st.sidebar.markdown("---")

# --- Charger un projet existant ---
projet_options = {p["nom_projet"]: p["id"] for p in projets_existants}
projet_selectionne = st.sidebar.selectbox("📂 Projets existants :", ["-- Sélectionner --"] + list(projet_options.keys()))

if st.sidebar.button("Charger ce projet", use_container_width=True):
    if projet_selectionne != "-- Sélectionner --":
        target_id = projet_options[projet_selectionne]
        try:
            response = supabase.table("projets").select("donnees").eq("id", target_id).eq("entreprise_id", st.session_state.entreprise_id).execute()
            if response.data:
                df_charge = pd.DataFrame(response.data[0]["donnees"])
                
                # Ajout des colonnes Gamme et Série si c'est un vieux projet
                if "Gamme" not in df_charge.columns: df_charge["Gamme"] = choix_gammes_dynamiques[0]
                if "Série" not in df_charge.columns: df_charge["Série"] = choix_series_dynamiques[0]

                colonnes_ordre = ["Repère", "Gamme", "Série", "Ouvrage", "Largeur (L)", "Hauteur (H)", "Qté", "Volet Roulant", "H Caisson", "Vitrage"]
                df_charge = df_charge.reindex(columns=colonnes_ordre)
                
                st.session_state.chassis_rows_v27 = df_charge
                st.session_state.current_project_name = projet_selectionne
                st.session_state.current_project_id = target_id
                st.rerun()
        except Exception as e:
            st.sidebar.error("Erreur lors du chargement.")

st.sidebar.markdown("---")

# --- Sauvegarder les modifications ---
st.sidebar.info(f"Projet actif : **{st.session_state.current_project_name}**")
if st.sidebar.button("💾 SAUVEGARDER LES MODIFICATIONS", type="primary", use_container_width=True):
    if st.session_state.current_project_id is not None:
        try:
            data_json = json.loads(st.session_state.chassis_rows_v27.to_json(orient="records", force_ascii=False))
            supabase.table("projets").update({"donnees": data_json}).eq("id", st.session_state.current_project_id).eq("entreprise_id", st.session_state.entreprise_id).execute()
            st.sidebar.success("Projet sauvegardé avec succès dans le cloud !")
        except Exception as e:
            st.sidebar.error(f"Erreur lors de la sauvegarde : {e}")
    else:
        st.sidebar.error("Veuillez d'abord créer ou charger un projet valide.")

# ==========================================
# FONCTIONS DE CALCUL ET INTERFACE 
# ==========================================
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Navigation")

menu_selection = st.sidebar.radio(
    "Modules :",
    [
        "📝 Saisie des Ouvrages", 
        "📐 Fiche Atelier & Débit", 
        "🪟 Carnet de Vitrage",
        "🛒 Quincaillerie & Joints", 
        "🛠️ Gestionnaire de Bibliothèque"
    ]
)

def safe_float(val, default=1.0):
    try:
        v = str(val).replace(',', '.').strip()
        if not v or v == '-': return default
        return float(v)
    except:
        return default

def evaluer_formule(formule, L, H, hC, nom_composant):
    if not formule or str(formule).strip() in ["-", ""]: return 0.0
    f = str(formule).replace('=', '').replace(',', '.').upper().strip()
    nom_comp_maj = str(nom_composant).upper()
    if "H" in f:
        if "COUVRE" in nom_comp_maj or "CJ" in nom_comp_maj: f = f.replace("H", str(H))
        else: f = f.replace("H", f"({H} - {hC})")
    if "L" in f: f = f.replace("L", str(L))
    f = re.sub(r'[^0-9\+\-\*\/\(\)\.]', '', f)
    try: return round(float(eval(f)), 1)
    except: return 0.0

def generer_reperes_auto(df):
    c_f = 0; c_p = 0; c_pf = 0; c_o = 0
    new_reperes = []
    for idx, row in df.iterrows():
        ouvr_raw = str(row.get("Ouvrage", "")).strip().upper()
        if not ouvr_raw: new_reperes.append("")
        elif ouvr_raw.startswith("PF"): c_pf += 1; new_reperes.append(f"PF{c_pf}")
        elif ouvr_raw.startswith("P"): c_p += 1; new_reperes.append(f"P{c_p}")
        elif ouvr_raw.startswith("F"): c_f += 1; new_reperes.append(f"F{c_f}")
        else: c_o += 1; new_reperes.append(f"O{c_o}")
    df_out = df.copy()
    df_out["Repère"] = new_reperes
    return df_out


NOM_PROJET = st.session_state.current_project_name

if menu_selection == "📝 Saisie des Ouvrages":
    st.markdown(f'<div class="section-header no-print">📝 Saisie des Ouvrages — {NOM_PROJET}</div>', unsafe_allow_html=True)

    # --- LISTES GLOBALES (Pour le tableau récapitulatif en bas) ---
    global_gammes = sorted(list(set([str(x.get("Gamme", "")).strip() for x in BIBLIOTHEQUE if str(x.get("Gamme", "")).strip() != ""])))
    global_series = sorted(list(set([str(x.get("Série", "")).strip() for x in BIBLIOTHEQUE if str(x.get("Série", "")).strip() != ""])))
    global_ouvrages = sorted(list(set([str(x.get("Type Ouvrage", "")).strip() for x in BIBLIOTHEQUE if str(x.get("Type Ouvrage", "")).strip() != ""])))

    if not global_gammes: global_gammes = ["-"]
    if not global_series: global_series = ["-"]
    if not global_ouvrages: global_ouvrages = ["-"]

    # ==========================================
    # ÉTAPE 1 : CHOIX DU MODÈLE (Dynamique, hors formulaire)
    # ==========================================
    # ==========================================
    # ÉTAPE 1 : CHOIX DU MODÈLE (Dynamique, hors formulaire)
    # ==========================================
    st.markdown("### ⚙️ 1. Choix du Modèle")
    
    # On ajoute une 4ème colonne pour l'image (les chiffres gèrent la largeur des colonnes)
    colA, colB, colC, col_img = st.columns([2, 2, 2, 1]) 
    
    # 1. Sélection de la Gamme
    sel_gamme = colA.selectbox("Gamme", options=global_gammes)
    
    # 2. Filtrage et sélection de la Série
    biblio_gamme = [x for x in BIBLIOTHEQUE if str(x.get("Gamme", "")).strip() == sel_gamme]
    choix_series_dyn = sorted(list(set([str(x.get("Série", "")).strip() for x in biblio_gamme if str(x.get("Série", "")).strip() != ""])))
    if not choix_series_dyn: choix_series_dyn = ["-"]
    sel_serie = colB.selectbox("Série", options=choix_series_dyn)
    
    # 3. Filtrage et sélection de l'Ouvrage
    biblio_serie = [x for x in biblio_gamme if str(x.get("Série", "")).strip() == sel_serie]
    choix_ouvrages_dyn = sorted(list(set([str(x.get("Type Ouvrage", "")).strip() for x in biblio_serie if str(x.get("Type Ouvrage", "")).strip() != ""])))
    if not choix_ouvrages_dyn: choix_ouvrages_dyn = ["-"]
    sel_ouvrage = colC.selectbox("Type d'Ouvrage", options=choix_ouvrages_dyn)

    # 4. Affichage de l'image correspondante
    with col_img:
        # Dictionnaire : relie le nom exact de ton ouvrage à l'URL d'une image
        # Il faudra remplacer ces liens par tes propres images hébergées ou locales !
        images_ouvrages = {
            "F C 2V": "https://cdn-icons-png.flaticon.com/512/3038/3038038.png", # Exemple icône fenêtre
            "F CM 3V": "https://cdn-icons-png.flaticon.com/512/3038/3038038.png",
            "PF C 2V": "https://cdn-icons-png.flaticon.com/512/1036/1036154.png"  # Exemple icône porte
        }
        
        # Image par défaut si l'ouvrage n'est pas dans le dictionnaire
        img_par_defaut = "https://cdn-icons-png.flaticon.com/512/1085/1085695.png" 
        
        url_img = images_ouvrages.get(sel_ouvrage, img_par_defaut)
        
        st.write("") # Petit espace pour aligner
        st.image(url_img, width=80)
    # ==========================================
    # ÉTAPE 2 : SAISIE DES DIMENSIONS (Dans le formulaire)
    # ==========================================
    st.markdown("### ⚡ 2. Dimensions & Ajout rapide")
    with st.form("form_ajout_rapide", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            n_largeur = st.number_input("Largeur (L) mm", min_value=100.0, value=1000.0, step=10.0)
            n_hauteur = st.number_input("Hauteur (H) mm", min_value=100.0, value=1000.0, step=10.0)
            
        with col2:
            n_qte = st.number_input("Quantité", min_value=1, value=1, step=1)
            n_vitrage = st.text_input("Vitrage", placeholder="ex: 4/16/4")
            
        with col3:
            n_volet = st.selectbox("Volet Roulant", options=["non", "caisson tunnel", "caisson mono-bloc"])
            n_h_caisson = st.number_input("H Caisson mm (si applicable)", min_value=0.0, value=0.0, step=10.0)

        submit_ajout = st.form_submit_button("➕ Ajouter ce châssis au projet", type="primary", use_container_width=True)

        if submit_ajout:
            nouvelle_ligne = pd.DataFrame([{
                "Repère": "",
                "Gamme": sel_gamme,       # Récupéré de l'étape 1
                "Série": sel_serie,       # Récupéré de l'étape 1
                "Ouvrage": sel_ouvrage,   # Récupéré de l'étape 1
                "Largeur (L)": float(n_largeur),
                "Hauteur (H)": float(n_hauteur),
                "Qté": int(n_qte),
                "Volet Roulant": n_volet,
                "H Caisson": float(n_h_caisson),
                "Vitrage": n_vitrage
            }])
            
            # Sécurité pour les anciens projets sans ces colonnes
            if "Gamme" not in st.session_state.chassis_rows_v27.columns:
                st.session_state.chassis_rows_v27["Gamme"] = sel_gamme
                st.session_state.chassis_rows_v27["Série"] = sel_serie

            st.session_state.chassis_rows_v27 = pd.concat([st.session_state.chassis_rows_v27, nouvelle_ligne], ignore_index=True)
            st.session_state.chassis_rows_v27 = generer_reperes_auto(st.session_state.chassis_rows_v27)
            st.rerun()

    st.markdown("---")
    st.markdown("### 📋 Listing des châssis (Modifiable)")

    # --- TABLEAU DE RÉVISION ---
    edited_df = st.data_editor(
        st.session_state.chassis_rows_v27,
        num_rows="dynamic",
        column_config={
            "Repère": st.column_config.TextColumn("N° (Auto)", disabled=True, width="small"),
            "Gamme": st.column_config.SelectboxColumn("Gamme", options=global_gammes),
            "Série": st.column_config.SelectboxColumn("Série", options=global_series),
            "Ouvrage": st.column_config.SelectboxColumn("Ouvrage", options=global_ouvrages),
            "Volet Roulant": st.column_config.SelectboxColumn(options=["non", "caisson tunnel", "caisson mono-bloc"]),
            "Vitrage": st.column_config.TextColumn("Vitrage (ex: 4/16/4)"),
        },
        use_container_width=True,
        key="project_editor_v27"
    )
    
    df_auto_calcule = generer_reperes_auto(edited_df)
    
    if not edited_df["Repère"].equals(df_auto_calcule["Repère"]):
        st.session_state.chassis_rows_v27 = df_auto_calcule
        st.rerun()
    else:
        st.session_state.chassis_rows_v27 = edited_df
        
    st.info("💡 N'oubliez pas de cliquer sur '💾 SAUVEGARDER LES MODIFICATIONS' dans le menu de gauche une fois votre saisie terminée.")
elif menu_selection == "📐 Fiche Atelier & Débit":
    st.markdown('<div class="section-header no-print">📏 Configuration de Coupe</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1: LONGUEUR_BRUTE = st.number_input("Longueur brute de barre (mm)", value=6500)
    with col2: EPAISSEUR_SCIE = st.number_input("Trait de scie (mm)", value=5)
    st.markdown('<div class="no-print" style="margin-top: 20px;">', unsafe_allow_html=True)
    btn_generer = st.button("⚡ GENERER LES PARCELLES COLORÉES", type="primary", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if btn_generer:
        edited_project = st.session_state.chassis_rows_v27
        dict_global_coupes = {}
        lignes_fiche_atelier = []
        match_trouve = False
        list_reperes = [str(row.get("Repère", "")).strip() for idx, row in edited_project.iterrows() if str(row.get("Repère", "")).strip() != ""]
        reperes_uniques = list(set(list_reperes))
        map_couleurs = {rep: PALETTE_COULEURS[idx % len(PALETTE_COULEURS)] for idx, rep in enumerate(reperes_uniques)}

        for index, row in edited_project.iterrows():
            type_ouvrage = str(row.get("Ouvrage", "")).strip()
            repere = str(row.get("Repère", "")).strip()
            if not type_ouvrage or not repere or row["Qté"] <= 0: continue
            L = float(row["Largeur (L)"])
            H = float(row["Hauteur (H)"])
            qte_ouvrage = int(row["Qté"])
            a_volet = str(row.get("Volet Roulant", "non")).lower()
            h_caisson = float(row.get("H Caisson", 0.0)) if a_volet == "caisson mono-bloc" else 0.0
            repere_qte_display = f"{repere} / {qte_ouvrage}<br><span style='font-size:11px; font-weight:normal; color:#374151;'>{type_ouvrage}</span>"
            
            for comp in BIBLIOTHEQUE:
                if clean_string(comp.get("Type Ouvrage", "")) == clean_string(type_ouvrage):
                    type_article = str(comp.get("Type", "")).strip().lower()
                    if type_article == "barre":
                        formule_brute = str(comp.get("Formule Long", "-")).strip()
                        ref_profil = str(comp.get("Ref", "INCONNU")).strip().upper()
                        la_serie = str(comp.get("Série", "SANS_SERIE")).strip()
                        designation_profil = str(comp.get("Composant", "")).strip()
                        qte_comp = safe_float(comp.get("Qté", 1), 1.0)
                        qte_totale_morceaux = int(qte_comp * qte_ouvrage)
                        longueur_coupe = evaluer_formule(formule_brute, L, H, h_caisson, designation_profil)
                        if longueur_coupe <= 0: continue
                        match_trouve = True
                        f_upper = formule_brute.upper()
                        if "H" in f_upper and "L" not in f_upper: orientation = "H"
                        elif "L" in f_upper and "H" not in f_upper: orientation = "L"
                        else: orientation = "Mix"
                        ref_display = f"{orientation}-{ref_profil}" if orientation != "Mix" else ref_profil
                        col_header_riche = f'<span style="font-size:10px; font-weight:normal; display:block; border-bottom:1px solid #713F12; padding-bottom:2px; margin-bottom:2px;">{designation_profil}</span>{ref_display}'
                        cle_ref = (la_serie, ref_profil)
                        if cle_ref not in dict_global_coupes: dict_global_coupes[cle_ref] = []
                        for _ in range(qte_totale_morceaux):
                            dict_global_coupes[cle_ref].append({"longueur": longueur_coupe, "repere": repere, "composant": designation_profil})
                        lignes_fiche_atelier.append({
                            "Série": la_serie, "Repère/Qté": repere_qte_display,
                            "ColHeader": col_header_riche, "Valeur": f"{int(longueur_coupe)}/{qte_totale_morceaux}"
                        })

        if match_trouve:
            st.markdown('<div class="section-header no-print">📐 Visualisation Documents d\'Atelier</div>', unsafe_allow_html=True)
            components.html("""<button onclick="window.parent.print()" style="background-color: #EF4444; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 14px; width: 100%;">🖨️ IMPRIMER LA FICHE D'ATELIER (Enregistrer en PDF)</button>""", height=60)
            st.markdown(f'<div class="projet-title">PROJET : {NOM_PROJET}</div>', unsafe_allow_html=True)
            st.markdown('<div class="excel-head-yellow">DETAIL PAR REPERE CHASSIS</div>', unsafe_allow_html=True)
            df_lignes = pd.DataFrame(lignes_fiche_atelier)
            if not df_lignes.empty:
                for serie in df_lignes['Série'].unique():
                    df_serie = df_lignes[df_lignes['Série'] == serie]
                    df_pivot = df_serie.pivot_table(index='Repère/Qté', columns='ColHeader', values='Valeur', aggfunc=lambda x: ' + '.join(x)).fillna("")
                    html_pivot = f'<div class="badge-serie">DÉBIT PAR CHÂSSIS :<br>{serie.upper()}</div><table class="print-table" style="margin-top: 0;"><thead><tr><th class="yellow-head" style="width: 120px;">REPÈRE / Qté<br><span style="font-size:10px; font-weight:normal;">Type Ouvrage</span></th>'
                    for col in df_pivot.columns: html_pivot += f'<th class="yellow-head">{col}</th>'
                    html_pivot += "</tr></thead><tbody>"
                    for rep, row_data in df_pivot.iterrows():
                        html_pivot += f'<tr><td style="font-weight: bold; text-align: center;">{rep}</td>'
                        for col in df_pivot.columns: html_pivot += f'<td class="center-text">{row_data[col]}</td>'
                        html_pivot += "</tr>"
                    html_pivot += "</tbody></table>"
                    st.markdown(html_pivot.replace('\n', ''), unsafe_allow_html=True)

            st.markdown('<div class="block-spacer"></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="excel-head-blue">✂️ REPARTITION REELLE DANS LES BARRES DE {int(LONGUEUR_BRUTE)} mm</div>', unsafe_allow_html=True)
            dict_total_barres_achetees = {}
            last_gamme_affichee = None
            html_coupes = '<table class="print-table" style="width: 100%;"><thead><tr><th style="width: 16%; text-align: center;">RÉFÉRENCE</th><th style="width: 50%; text-align: center;">PLAN DE COUPE</th><th style="width: 5%; text-align: center;">QTÉ</th><th style="width: 9%; text-align: center;">UTILE</th><th style="width: 9%; text-align: center;">CHUTE</th><th style="width: 11%; text-align: center;">% PERTE</th></tr></thead><tbody>'
            for (serie, ref), coupes in sorted(dict_global_coupes.items(), key=lambda x: (x[0][0], x[0][1])):
                if serie != last_gamme_affichee:
                    html_coupes += f'<tr style="background-color: #4B5563; color: white; font-weight: bold; border-bottom: 2px solid #111827;"><td colspan="6" style="padding: 8px 10px;">GAMME / SÉRIE : {serie.upper()}</td></tr>'
                    last_gamme_affichee = serie
                coupes_triees = sorted(coupes, key=lambda x: x["longueur"], reverse=True)
                barres_brutes = []
                for c in coupes_triees:
                    place_trouvee = False
                    for b in barres_brutes:
                        espace_occupe = sum([m["longueur"] for m in b]) + (len(b) * EPAISSEUR_SCIE)
                        if (c["longueur"] + EPAISSEUR_SCIE) <= (LONGUEUR_BRUTE - espace_occupe):
                            b.append(c); place_trouvee = True; break
                    if not place_trouvee: barres_brutes.append([c])
                dict_total_barres_achetees[(serie, ref)] = len(barres_brutes)
                grouped_bars = []
                for b in barres_brutes:
                    matched = False
                    for gb in grouped_bars:
                        if len(b) == len(gb['pieces']):
                            is_identical = True
                            for p1, p2 in zip(b, gb['pieces']):
                                if p1['longueur'] != p2['longueur'] or p1['repere'] != p2['repere']: is_identical = False; break
                            if is_identical: gb['qty'] += 1; matched = True; break
                    if not matched: grouped_bars.append({'pieces': b, 'qty': 1})
                total_barres_pour_ref = 0
                b_idx = 1
                for gb in grouped_bars:
                    barre = gb['pieces']; qte_barre = gb['qty']; total_barres_pour_ref += qte_barre
                    somme_profils = sum([m["longueur"] for m in barre]); somme_scies = len(barre) * EPAISSEUR_SCIE
                    total_consomme = somme_profils + somme_scies; chute_restante = max(0, LONGUEUR_BRUTE - total_consomme)
                    pct_perte = (chute_restante / LONGUEUR_BRUTE) * 100
                    html_barre_div = '<div class="bar-container">'
                    for morceau in barre:
                        moceau_lg = morceau["longueur"]; rep = morceau["repere"]; comp_name = morceau["composant"]
                        couleur = map_couleurs.get(rep, "#3B82F6")
                        pct_largeur = ((moceau_lg + EPAISSEUR_SCIE) / LONGUEUR_BRUTE) * 100
                        html_barre_div += f'<div class="bar-segment" style="width: {pct_largeur}%; background-color: {couleur};" title="{rep} - {comp_name} ({int(moceau_lg)}mm)">{int(moceau_lg)}</div>'
                    if chute_restante > 0: html_barre_div += f'<div class="bar-chute" style="width: {(chute_restante/LONGUEUR_BRUTE)*100}%;"></div>'
                    html_barre_div += '</div>'
                    html_coupes += f'<tr><td class="center-text">{ref} (B{b_idx})</td><td style="padding: 4px;">{html_barre_div}</td><td class="center-text" style="font-weight: bold;">{qte_barre}</td><td class="center-text">{int(total_consomme)}</td><td class="center-text">{int(chute_restante)}</td><td class="center-text">{pct_perte:.1f}%</td></tr>'
                    b_idx += 1
                html_coupes += f'<tr style="background-color: #F9FAFB; font-weight: bold; border-bottom: 2px solid #D1D5DB;"><td>TOTAL {ref}</td><td colspan="5">{total_barres_pour_ref} Barre(s) ({serie.upper()}) de {int(LONGUEUR_BRUTE)} mm</td></tr>'
            html_coupes += "</tbody></table>"
            st.markdown(html_coupes.replace('\n', ''), unsafe_allow_html=True)
            st.markdown('<div class="block-spacer"></div>', unsafe_allow_html=True)
            st.markdown('<div class="excel-head-green">📦 RÉCAPITULATIF DE COMMANDE DES PROFILÉS</div>', unsafe_allow_html=True)
            html_recap = '<table class="print-table" style="width: 50%;"><thead><tr><th>Gamme / Série</th><th>Référence Alu</th><th class="center-text">Total de barres (' + str(LONGUEUR_BRUTE/1000) + 'm)</th></tr></thead><tbody>'
            for (serie, ref), qte_b in dict_total_barres_achetees.items():
                html_recap += f"<tr><td>{serie}</td><td>{ref}</td><td class='center-text' style='font-weight: bold;'>{qte_b}</td></tr>"
            html_recap += "</tbody></table>"
            st.markdown(html_recap.replace('\n', ''), unsafe_allow_html=True)
        else:
            st.error("⚠️ Aucun profilé de type 'Barre' trouvé pour cet ouvrage.")

elif menu_selection == "🪟 Carnet de Vitrage":
    st.markdown('<div class="section-header no-print">🪟 Carnet de Vitrage (Miroitier)</div>', unsafe_allow_html=True)
    st.markdown('<div class="no-print" style="margin-top: 10px; margin-bottom: 20px;">', unsafe_allow_html=True)
    btn_calculer_vitrage = st.button("🔄 CALCULER LES VITRAGES", type="primary", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if btn_calculer_vitrage:
        edited_project = st.session_state.chassis_rows_v27
        list_vitrages = []
        for index, row in edited_project.iterrows():
            type_ouvrage = str(row.get("Ouvrage", "")).strip()
            repere = str(row.get("Repère", "")).strip()
            if not type_ouvrage or not repere or row["Qté"] <= 0: continue
            L = float(row["Largeur (L)"])
            H = float(row["Hauteur (H)"])
            qte_ouvrage = int(row["Qté"])
            type_vitrage_saisi = str(row.get("Vitrage", "")).strip()
            a_volet = str(row.get("Volet Roulant", "non")).lower()
            h_caisson = float(row.get("H Caisson", 0.0)) if a_volet == "caisson mono-bloc" else 0.0
            vitrage_rows = [comp for comp in BIBLIOTHEQUE if clean_string(comp.get("Type Ouvrage", "")) == clean_string(type_ouvrage) and str(comp.get("Type", "")).strip().lower() in ["vitrage", "verre"]]
            list_w = []; list_h = []
            for comp in vitrage_rows:
                designation = str(comp.get("Composant", "Vitrage")).strip()
                f_vit = str(comp.get("Formule Long", "")).upper().replace('=', '').replace('X', '*')
                if not f_vit: f_vit = str(comp.get("Formule Coupe", "")).upper().replace('=', '').replace('X', '*')
                qte_comp = safe_float(comp.get("Qté", 1), 1.0)
                qte_totale = int(qte_comp * qte_ouvrage)
                if '*' in f_vit and 'L' in f_vit and 'H' in f_vit:
                    parts = f_vit.split('*')
                    v_L = 0; v_H = 0
                    for p in parts:
                        if 'L' in p: v_L = evaluer_formule(p, L, H, h_caisson, designation)
                        elif 'H' in p: v_H = evaluer_formule(p, L, H, h_caisson, designation)
                    if v_L > 0 and v_H > 0:
                        list_vitrages.append({
                            "Repère": repere, "Ouvrage": type_ouvrage, "Désignation": designation,
                            "Type Vitrage": type_vitrage_saisi if type_vitrage_saisi else "Standard",
                            "Largeur (mm)": int(v_L), "Hauteur (mm)": int(v_H), "Qté": qte_totale,
                            "Surf. U. (m²)": round((v_L * v_H) / 1000000.0, 2), "Surf. Totale (m²)": round(((v_L * v_H) / 1000000.0) * qte_totale, 2)
                        })
                else:
                    val = evaluer_formule(f_vit, L, H, h_caisson, designation)
                    if 'L' in f_vit or "LARGEUR" in designation.upper() or designation.upper().endswith(" L"):
                        list_w.append({"des": designation, "val": val, "qte": qte_totale})
                    elif 'H' in f_vit or "HAUTEUR" in designation.upper() or designation.upper().endswith(" H"):
                        list_h.append({"des": designation, "val": val, "qte": qte_totale})
                    else:
                        if "HAUTEUR" in designation.upper() or "H" in designation.upper(): list_h.append({"des": designation, "val": val, "qte": qte_totale})
                        else: list_w.append({"des": designation, "val": val, "qte": qte_totale})
            for idx in range(max(len(list_w), len(list_h))):
                w_item = list_w[idx] if idx < len(list_w) else {"des": "Vitrage", "val": 0, "qte": qte_ouvrage}
                h_item = list_h[idx] if idx < len(list_h) else {"des": "Vitrage", "val": 0, "qte": qte_ouvrage}
                v_L = w_item["val"]; v_H = h_item["val"]
                if v_L == 0: v_L = v_H
                if v_H == 0: v_H = v_L
                if v_L > 0 and v_H > 0:
                    final_des = w_item["des"].replace("Largeur", "").replace("largeur", "").replace("L", "").replace("H", "").replace("Hauteur", "").replace("hauteur", "").strip()
                    if not final_des or final_des == "-": final_des = "Vitrage Ouvrage"
                    qte_final = max(w_item["qte"], h_item["qte"])
                    surf_u = (v_L * v_H) / 1000000.0
                    surf_tot = surf_u * qte_final
                    list_vitrages.append({
                        "Repère": repere, "Ouvrage": type_ouvrage, "Désignation": final_des,
                        "Type Vitrage": type_vitrage_saisi if type_vitrage_saisi else "Standard",
                        "Largeur (mm)": int(v_L), "Hauteur (mm)": int(v_H), "Qté": qte_final,
                        "Surf. U. (m²)": round(surf_u, 2), "Surf. Totale (m²)": round(surf_tot, 2)
                    })

        components.html("""<button onclick="window.parent.print()" style="background-color: #EF4444; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 14px; width: 100%;">🖨️ IMPRIMER LA COMMANDE MIROITIER</button>""", height=60)
        st.markdown(f'<div class="projet-title">PROJET : {NOM_PROJET}</div>', unsafe_allow_html=True)
        st.markdown('<div class="excel-head-blue">🪟 CARNET DE VITRAGE (COMMANDE MIROITIER)</div>', unsafe_allow_html=True)
        if list_vitrages:
            df_vitrage = pd.DataFrame(list_vitrages)
            surface_projet_totale = df_vitrage["Surf. Totale (m²)"].sum()
            html_vitrage = '<table class="print-table" style="width: 100%;"><thead><tr><th>Repère</th><th>Ouvrage</th><th>Détail Vitre</th><th>Type Vitrage</th><th class="center-text">Largeur (mm)</th><th class="center-text">Hauteur (mm)</th><th class="center-text">Qté</th><th class="center-text">Surf. U. (m²)</th><th class="center-text">Surf. Totale (m²)</th></tr></thead><tbody>'
            for idx, v in df_vitrage.iterrows():
                html_vitrage += f'<tr><td><b>{v["Repère"]}</b></td><td>{v["Ouvrage"]}</td><td>{v["Désignation"]}</td><td>{v["Type Vitrage"]}</td><td class="center-text" style="color: #1E40AF; font-weight:bold;">{v["Largeur (mm)"]}</td><td class="center-text" style="color: #DC2626; font-weight:bold;">{v["Hauteur (mm)"]}</td><td class="center-text" style="font-weight:bold; font-size:15px;">{v["Qté"]}</td><td class="center-text">{v["Surf. U. (m²)"]:.2f}</td><td class="center-text">{v["Surf. Totale (m²)"]:.2f}</td></tr>'
            html_vitrage += f'<tr style="background-color: #DBEAFE; font-weight: bold;"><td colspan="8" style="text-align: right;">SURFACE TOTALE VITRAGE :</td><td class="center-text">{surface_projet_totale:.2f} m²</td></tr>'
            html_vitrage += '</tbody></table>'
            st.markdown(html_vitrage.replace('\n', ''), unsafe_allow_html=True)
        else:
            st.info("Aucun vitrage n'a été détecté. Vérifiez vos données de saisie.")

elif menu_selection == "🛒 Quincaillerie & Joints":
    st.markdown('<div class="section-header no-print">🛒 Quincaillerie & Joints (Accessoires)</div>', unsafe_allow_html=True)
    st.markdown('<div class="no-print" style="margin-top: 10px; margin-bottom: 20px;">', unsafe_allow_html=True)
    btn_calculer_acc = st.button("🔄 CALCULER LES BESOINS", type="primary", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if btn_calculer_acc:
        edited_project = st.session_state.chassis_rows_v27
        list_recap_chassis = []; list_accessoires = []; list_joints = []
        for index, row in edited_project.iterrows():
            type_ouvrage = str(row.get("Ouvrage", "")).strip()
            repere = str(row.get("Repère", "")).strip()
            if not type_ouvrage or row["Qté"] <= 0: continue
            L = float(row["Largeur (L)"])
            H = float(row["Hauteur (H)"])
            qte_ouvrage = int(row["Qté"])
            a_volet = str(row.get("Volet Roulant", "non")).lower()
            h_caisson = float(row.get("H Caisson", 0.0)) if a_volet == "caisson mono-bloc" else 0.0
            for comp in BIBLIOTHEQUE:
                if clean_string(comp.get("Type Ouvrage", "")) == clean_string(type_ouvrage):
                    type_article = str(comp.get("Type", "")).strip().lower()
                    designation = str(comp.get("Composant", "")).strip()
                    serie = str(comp.get("Série", "")).strip()
                    ref_comp = str(comp.get("Ref", "")).strip()
                    unite = str(comp.get("Unité", "U")).strip()
                    qte_comp = safe_float(comp.get("Qté", 1), 1.0)
                    if "joint" in type_article or "brosse" in type_article:
                        longueur_mm = evaluer_formule(comp.get("Formule Long", ""), L, H, h_caisson, designation)
                        if longueur_mm <= 0: longueur_mm = evaluer_formule(comp.get("Formule Coupe", ""), L, H, h_caisson, designation)
                        total_mm = longueur_mm * qte_comp * qte_ouvrage
                        if total_mm > 0:
                            total_m = total_mm / 1000.0
                            list_recap_chassis.append({
                                "Repère": repere, "Ouvrage": type_ouvrage, "Composant": designation,
                                "Ref": ref_comp, "Qté": f"{total_m:.2f}", "Unité": "m", "Série": serie
                            })
                            list_joints.append({"Série": serie, "Référence": ref_comp, "Désignation": designation, "Quantité Totale (m)": total_m})
                    elif "accessoire" in type_article or "quinc" in type_article:
                        total_qty = qte_comp * qte_ouvrage
                        if total_qty > 0:
                            list_recap_chassis.append({
                                "Repère": repere, "Ouvrage": type_ouvrage, "Composant": designation,
                                "Ref": ref_comp, "Qté": f"{int(total_qty)}", "Unité": unite if unite else "U", "Série": serie
                            })
                            list_accessoires.append({"Série": serie, "Référence": ref_comp, "Désignation": designation, "Quantité": total_qty})

        components.html("""<button onclick="window.parent.print()" style="background-color: #EF4444; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; font-size: 14px; width: 100%;">🖨️ IMPRIMER TOUTE LA COMMANDE QUINCAILLERIE</button>""", height=60)
        st.markdown(f'<div class="projet-title">PROJET : {NOM_PROJET}</div>', unsafe_allow_html=True)
        st.markdown('<div class="excel-head-yellow">📋 DÉTAILS ACCESSOIRES & JOINTS PAR REPERE (CHASSIS)</div>', unsafe_allow_html=True)
        if list_recap_chassis:
            df_recap_chassis = pd.DataFrame(list_recap_chassis)
            df_recap_chassis["Ref"] = df_recap_chassis["Ref"].fillna("-")
            html_chassis = '<table class="print-table" style="width: 100%;"><thead><tr><th>Repère</th><th>Ouvrage</th><th>Composant</th><th>Réf</th><th class="center-text">Qté</th><th class="center-text">Unité</th></tr></thead><tbody>'
            for idx, row_item in df_recap_chassis.iterrows():
                html_chassis += f'<tr><td><b>{row_item["Repère"]}</b></td><td>{row_item["Ouvrage"]}</td><td>{row_item["Composant"]}</td><td>{row_item["Ref"]}</td><td class="center-text" style="font-weight:bold;">{row_item["Qté"]}</td><td class="center-text">{row_item["Unité"]}</td></tr>'
            html_chassis += '</tbody></table>'
            st.markdown(html_chassis.replace('\n', ''), unsafe_allow_html=True)
        else: st.info("Aucun composant n'a été détecté pour ces ouvrages.")

        st.markdown('<div class="block-spacer"></div>', unsafe_allow_html=True)
        st.markdown('<div class="excel-head-blue">🔗 QUINCAILLERIE & ACCESSOIRES (CUMUL GLOBAL DU PROJET)</div>', unsafe_allow_html=True)
        if list_accessoires:
            df_acc = pd.DataFrame(list_accessoires)
            df_acc["Référence"] = df_acc["Référence"].fillna(""); df_acc["Série"] = df_acc["Série"].fillna("")
            df_acc_grouped = df_acc.groupby(["Série", "Référence", "Désignation"], dropna=False, as_index=False)["Quantité"].sum()
            html_acc = '<table class="print-table" style="width: 100%;"><thead><tr><th>Gamme / Série</th><th>Référence</th><th>Désignation de l\'Accessoire</th><th class="center-text">Quantité Globale</th></tr></thead><tbody>'
            for idx, a in df_acc_grouped.iterrows():
                html_acc += f'<tr><td>{a["Série"]}</td><td>{a["Référence"]}</td><td>{a["Désignation"]}</td><td class="center-text" style="font-weight:bold;">{int(a["Quantité"])} U</td></tr>'
            html_acc += '</tbody></table>'
            st.markdown(html_acc.replace('\n', ''), unsafe_allow_html=True)

        st.markdown('<div class="block-spacer"></div>', unsafe_allow_html=True)
        st.markdown('<div class="excel-head-gray">〰️ JOINTS & BROSSE (CUMUL GLOBAL DU PROJET)</div>', unsafe_allow_html=True)
        if list_joints:
            df_joints = pd.DataFrame(list_joints)
            df_joints["Référence"] = df_joints["Référence"].fillna(""); df_joints["Série"] = df_joints["Série"].fillna("")
            df_joints_grouped = df_joints.groupby(["Série", "Référence", "Désignation"], dropna=False, as_index=False)["Quantité Totale (m)"].sum()
            html_joints = '<table class="print-table" style="width: 100%;"><thead><tr><th>Gamme / Série</th><th>Référence</th><th>Désignation du Joint</th><th class="center-text">Longueur Totale (Mètres)</th></tr></thead><tbody>'
            for idx, j in df_joints_grouped.iterrows():
                html_joints += f'<tr><td>{j["Série"]}</td><td>{j["Référence"]}</td><td>{j["Désignation"]}</td><td class="center-text" style="font-weight:bold;">{j["Quantité Totale (m)"]:.2f} m</td></tr>'
            html_joints += '</tbody></table>'
            st.markdown(html_joints.replace('\n', ''), unsafe_allow_html=True)

elif menu_selection == "🛠️ Gestionnaire de Bibliothèque":
    st.markdown('<div class="section-header no-print">🛠️ Catalogue Actuel Emporté</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(BIBLIOTHEQUE), use_container_width=True)