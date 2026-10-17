import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import os

# Store data in dictionary
def store_data_to_dict(data, growing_seasons, out_of_sample=False):
    dfs = {}
    for crop in growing_seasons.keys():
        
        if out_of_sample:
            data_idx = data[["Province", "year"]].copy()
            data_climate = data.filter(regex='^(pet_|tx_|pr_|m_)')
            dfs[crop] = pd.concat([data_idx, data_climate], axis=1)
        else:
            data_idx = data[["Province", "year", crop]]
            data_climate = data.filter(regex='^(pet_|tx_|pr_|m_)')
            dfs[crop] = pd.concat([data_idx, data_climate], axis=1)
            dfs[crop] = dfs[crop].rename(columns={crop: "yield"})
        
    return dfs

# Obtain trends and detrend
def detrend(dfs):

    dfs_detrended = {}
    trend_models = {}
    for crop, data in dfs.items():
        
        # Get provinces
        unique_provinces = np.unique(data['Province'])
        
        # Get trend
        data_list = []
        models = {}
        for province in unique_provinces:
            
            # Subset data
            province_index = data['Province'] == province
            province_data = data.loc[province_index, ['Province', 'year', 'yield']].copy().dropna()
            
            # Get trend
            data_model = province_data.copy()
            data_model['year2'] = data_model['year']**2
            data_model['year3'] = data_model['year']**3
            data_model['year4'] = data_model['year']**4
            model = LinearRegression()
            model.fit(data_model[['year', 'year2', 'year3']], data_model['yield'])
            province_data['yield_smoothed'] = model.predict(data_model[['year', 'year2', 'year3']])
            
            #province_data['yield_smoothed'] = lowess(province_data['yield'], province_data['year'])[:, 1]
            province_data['yield_detrended'] = province_data['yield'] - province_data['yield_smoothed']
            data_list.append(province_data)
            models[province] = model
        
        # Concat new data and store in dictionary
        data_new = pd.concat(data_list).drop(columns='yield')
        dfs_detrended[crop] = pd.merge(data, data_new, how='left', on=['Province', 'year'])
        trend_models[crop] = models
        
    return dfs_detrended, trend_models

# Process data
def process_data(dfs_detrended, growing_seasons, out_of_sample=False):
        
    # Add lag
    def add_lag(data):

        # Create a lagged DataFrame by shifting the data by one year
        df_lagged = data.copy()
        df_lagged['year'] = df_lagged['year'] + 1  # Shift year by 1 to align with the next year
        df_lagged['lag_id'] = df_lagged['Province'] + '_' + (df_lagged['year']).astype(str)

        # Create a similar identifier in the original DataFrame for merging
        data['current_id'] = data['Province'] + '_' + data['year'].astype(str)
        
        # Drop unnecessary columns to take lag of
        df_lagged = df_lagged.drop(columns=['year', 'Province'])

        # Merge the lagged data with the original DataFrame
        data = data.merge(df_lagged, left_on='current_id', right_on='lag_id', suffixes=('', '_lag'))

        # Drop the temporary columns used for merging
        data = data.drop(columns=['current_id', 'lag_id'])
        
        return data   
        
    # Align months with harvesting period
    def align_months_with_harvest_period(row, growing_season):
            
        # Get harvesting month
        plant_month = growing_season[0]
        harvest_month = growing_season[1]
        
        # Specify climate variables
        clim_vars = ['pet', 'pr', 'tx', 'm']
        
        # Get copy of row
        new_row = row.copy()
        
        # Iterate over months
        for i in range(1, 13):
            
            # Select month in the year corresponding to harvest month minus i
            month = harvest_month - i + 1
            if month >= 1: # If the month falls within the current year
                for clim_var in clim_vars:
                    new_row[f'{clim_var}_{i}'] = row[f'{clim_var}_{month}']
            else: # If the month falls within the previous year
                lagged_month = 12 + month
                for clim_var in clim_vars:
                    new_row[f'{clim_var}_{i}'] = row[f'{clim_var}_{lagged_month}_lag']
                    
        return new_row
        
    # Add growing season averages
    def add_growing_season_avg(row, growing_season):
        
        # Get harvesting month
        plant_month = growing_season[0]
        harvest_month = growing_season[1]
        
        # Get duration
        growing_season_duration = harvest_month - plant_month
        if growing_season_duration <= 0:
            growing_season_duration = growing_season_duration + 12
        
        # Specify climate variables
        clim_vars = ['pet', 'pr', 'tx', 'm']
        
        # Get copy of row
        new_row = row.copy()
        
        # Iterate over variables
        for clim_var in clim_vars:
            
            vals = []
            
            # Iterate over growing_season months
            for i in range(1, growing_season_duration):
                
                # Collect values
                vals.append(new_row[f'{clim_var}_{i}'])
            
            # Compute and store average
            growing_avg = np.mean(vals)
            new_row[f'{clim_var}_growing'] = growing_avg
            
        return new_row   

    dfs_aligned = {}
    for crop, data in dfs_detrended.items():
        data_with_lag = add_lag(data)

        # In out-of-sample mode, incomplete previous-year rows can leave *_lag gaps.
        # Fill these gaps from same-year values so current-year inference remains available.
        if out_of_sample:
            lag_cols = [col for col in data_with_lag.columns if col.endswith('_lag')]
            for lag_col in lag_cols:
                base_col = lag_col[:-4]
                if base_col in data_with_lag.columns:
                    data_with_lag[lag_col] = data_with_lag[lag_col].fillna(data_with_lag[base_col])

        growing_season = growing_seasons[crop]
        data_aligned = data_with_lag.apply(align_months_with_harvest_period, args=(growing_season,), axis=1)
        data_align_with_growing = data_aligned.apply(add_growing_season_avg, args=(growing_season,), axis=1)
        dfs_aligned[crop] = data_align_with_growing
        
        
    # Get data that is ready for modeling
    def get_model_data(data, out_of_sample=False):
        
        if out_of_sample:
            data_clean = data.drop(columns=[col for col in data.columns.values if col.endswith('_lag')]).dropna()
            regions = data_clean['Province'].values
            years = data_clean['year'].values
            X = data_clean.drop(columns=['Province'])
            
            return data_clean, regions, years, X
            
        else:
            data_clean = data.drop(columns=[col for col in data.columns.values if col.endswith('_lag')]).dropna()
            y = data_clean['yield_detrended'].values
            regions = data_clean['Province'].values
            years = data_clean['year'].values
            X = data_clean.drop(columns=['yield', 'yield_smoothed', 'yield_detrended', 'Province'])
            
            return data_clean, y, regions, years, X

    data_model = {}
    for crop, data in dfs_aligned.items():
        data_model[crop] = get_model_data(data, out_of_sample)
        
    return data_model

# Store predictions
def store_predictions(dfs_predictions, output_path="predicted_yields.csv"):
    
    data_list = []
    
    # Iterate over crops
    for crop, data in dfs_predictions.items():
        data_copy = data.copy()
        data_copy['crop'] = np.repeat(crop, data.shape[0])
        data_list.append(data_copy)
        
    # Combine data - This creates the variable 'full_data'
    full_data = pd.concat(data_list)
    
    try:
        # Check if the folder exists right before saving
        folder = os.path.dirname(output_path)
        if folder and not os.path.exists(folder):
            print(f"DEBUG: Creating folder {folder}")
            os.makedirs(folder, exist_ok=True)

        print(f"DEBUG: Attempting to write CSV to {output_path}...")
        
        # FIX: Changed 'final_df' to 'full_data' to match line 13
        full_data.to_csv(output_path, index=False)
        
        if os.path.exists(output_path):
            print(f"DEBUG: ✅ FILE CONFIRMED on disk at {output_path}")
            print(f"Successfully wrote CSV to: {output_path}")
        else:
            print("DEBUG: ❌ to_csv finished but file DOES NOT EXIST.")
            
    except Exception as e:
        print(f"DEBUG: ❌ FAILED TO WRITE CSV. Error: {e}")