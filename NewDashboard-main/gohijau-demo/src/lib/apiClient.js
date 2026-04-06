// src/lib/apiClient.js
const BASE_URL = 'https://services.gohijau.org';

export default {
  get: async (endpoint) => {
    try {
      const response = await fetch(`${BASE_URL}${endpoint}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      // Wrapping in { data } so it matches how Axios formats responses, 
      // preventing the need to rewrite your Vue components.
      return { data }; 
    } catch (error) {
      console.error("API Connection Error:", error);
      throw error; // This will trigger the catch block in your Vue components
    }
  }
};