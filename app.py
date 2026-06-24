
import streamlit as st
import pandas as pd
import os
from io import StringIO

st.set_page_config(page_title="SMS Operator Counter", layout="centered")
st.title("SMS Operator Counter")

# ─── File Upload ──────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Tracking File")
    tracking_file = st.file_uploader("Upload tracking file", type=["csv", "xlsx"], key="tracking")

with col2:
    st.subheader("Reference File")
    reference_file = st.file_uploader("Upload reference file", type=["csv", "xlsx"], key="reference")

# ─── Dynamic Excel Sheet Selection ────────────────────────────────────────────

selected_sheet = None
if reference_file and reference_file.name.endswith(".xlsx"):
    try:
        excel_file = pd.ExcelFile(reference_file)
        sheet_names = excel_file.sheet_names
        
        selected_sheet = st.selectbox(
            "Select Reference Sheet", 
            options=sheet_names,
            index=0,
            help="Choose the specific sheet that contains all operator columns."
        )
    except Exception as e:
        st.error(f"Error reading Excel sheets: {e}")

# ─── Core Normalization Logic ─────────────────────────────────────────────────

def to_int_str(val):
    try:
        return str(int(float(val)))
    except (ValueError, TypeError):
        return str(val).strip()

# ─── Read Dataframes Helper (Fixed to Match Standalone Exactly) ───────────────

def load_file(uploaded_file, is_tracking=False, sheet_name=None):
    if uploaded_file.name.endswith(".xlsx"):
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, sheet_name=sheet_name if sheet_name else 0)
    
    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            raw_text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raw_text = raw_bytes.decode("utf-8", errors="replace")

    all_lines = raw_text.splitlines()

    if is_tracking:
        # Find the actual header line by locating the line that contains
        # both 'destination' and 'source' (case-insensitive). Everything
        # before that line is treated as metadata/comments.
        header_idx = None
        for i, line in enumerate(all_lines):
            low = line.lower()
            if "destination" in low and "source" in low:
                header_idx = i
                break

        if header_idx is not None:
            lines = [l for l in all_lines[header_idx:] if l.strip()]
        else:
            # Fallback: strip comment and empty lines
            lines = [l for l in all_lines if l.strip() and not l.strip().startswith("#")]
    else:
        lines = [l for l in all_lines if l.strip() and not l.strip().startswith("#")]

    clean_text = "\n".join(lines)

        
    header_line = lines[0] if lines else ""
    delimiter = ","
    for sep in (",", ";", "\t", "|"):
        if sep in header_line:
            delimiter = sep
            break

    return pd.read_csv(
        StringIO(clean_text),
        sep=delimiter,
        engine="python",
        on_bad_lines="skip"
    )

# ─── Main Processing Block ────────────────────────────────────────────────────

if tracking_file and reference_file:
    try:
        tracking_df = load_file(tracking_file, is_tracking=True)
        reference_df = load_file(reference_file, is_tracking=False, sheet_name=selected_sheet)
        
        # Clean columns structure
        tracking_df.columns = tracking_df.columns.astype(str).str.strip()
        reference_df.columns = reference_df.columns.astype(str).str.strip()
        
        person_name = os.path.splitext(reference_file.name)[0].replace("all numbers", "").strip().capitalize()
        
        st.divider()
        st.header(f"Analysis for Name: {person_name}")
        
        # Check tracking file required headers
        dst_col = next((c for c in tracking_df.columns if c.lower() == "destination"), None)
        src_col = next((c for c in tracking_df.columns if c.lower() == "source"), None)
        text_col = next((c for c in tracking_df.columns if c.lower() in ["text", "message"]), None) 
        
        if not dst_col or not src_col:
            st.error("❌ Tracking file must contain both 'Destination' and 'Source' columns.")
        else:
            # =====================================================================
            # TABLE 1: ORIGINAL LOGIC (Unchanged)
            # =====================================================================
            st.subheader("1. Source Analysis Matrix")
            # Normalize target columns using your exact business logic
            tracking_df['_dest_norm'] = tracking_df[dst_col].apply(to_int_str)
            tracking_df['_source'] = tracking_df[src_col].astype(str).str.strip()
            
            unique_sources = sorted(tracking_df['_source'].unique())
            operators = [col for col in reference_df.columns if not col.lower().startswith("unnamed:")]
            
            # Execute calculation matrices
            rows = []
            for operator in operators:
                numbers_set = set(reference_df[operator].dropna().apply(to_int_str))
                matched = tracking_df[tracking_df['_dest_norm'].isin(numbers_set)]
                
                row = {'Operator': operator, 'Total': len(matched)}
                for source in unique_sources:
                    row[source] = (matched['_source'] == source).sum()
                rows.append(row)
            
            result_df = pd.DataFrame(rows).set_index('Operator')
            
            # Keep only source columns that have at least 1 match across all operators
            source_cols = [c for c in result_df.columns if c != 'Total' and result_df[c].sum() > 0]
            clean_df = result_df[['Total'] + source_cols].sort_values('Total', ascending=False)
            
            # ── Display Summary Matrix as a Static Table ──────────────────────
            st.table(clean_df)
            
            # ── Export System ─────────────────────────────────────────────────
            export_ready = clean_df.reset_index()
            export_ready.insert(0, "File/Name", person_name)
            
            st.download_button(
                label=f"Export {person_name} Master Table Report",
                data=export_ready.to_csv(index=False).encode("utf-8"),
                file_name=f"{person_name.lower()}_operator_source_matrix.csv",
                mime="text/csv",
                use_container_width=True,
                key="download_source" 
            )
            
            # =====================================================================
            # TABLE 2: TEXT STRING SEARCH
            # =====================================================================
            st.divider()
            st.subheader("2. Text Search Matrix")
            
            search_input = st.text_input(
                "Enter strings to search in the Text column (comma-separated):", 
                value="apple, microsoft, amazon"
            )
            
            app_strings = [s.strip() for s in search_input.split(",") if s.strip()]
            
            if app_strings:
                if not text_col:
                    st.warning("⚠️ Could not find a 'Text' or 'Message' column in the tracking file to perform the search.")
                else:
                    tracking_df['_text'] = tracking_df[text_col].astype(str)
                    
                    rows_text = []
                    for operator in operators:
                        numbers_set = set(reference_df[operator].dropna().apply(to_int_str))
                        matched = tracking_df[tracking_df['_dest_norm'].isin(numbers_set)]
                        
                        row = {'Operator': operator}
                        total_occurrences = 0
                        
                        for app_text in app_strings:
                            occurrences = matched['_text'].str.contains(app_text, case=False, na=False).sum()
                            row[app_text] = occurrences
                            total_occurrences += occurrences
                            
                        row['Total'] = total_occurrences
                        rows_text.append(row)
                    
                    result_text_df = pd.DataFrame(rows_text).set_index('Operator')
                    
                    # Reorder keeping 'Total' first
                    column_order = ['Total'] + app_strings
                    clean_text_df = result_text_df[column_order].sort_values('Total', ascending=False)
                    
                    st.table(clean_text_df)
                    
                    export_ready_text = clean_text_df.reset_index()
                    export_ready_text.insert(0, "File/Name", person_name)
                    
                    st.download_button(
                        label=f"Export {person_name} Text Search Report",
                        data=export_ready_text.to_csv(index=False).encode("utf-8"),
                        file_name=f"{person_name.lower()}_text_search_matrix.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key="download_text" 
                    )
            
    except Exception as e:
        st.error(f"An error occurred while analyzing the files: {e}")
