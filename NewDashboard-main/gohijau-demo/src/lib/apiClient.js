// src/lib/apiClient.js
const BASE_URL = 'http://localhost:5137'; // Make sure this matches your C# server port

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
      return { data }; 
    } catch (error) {
      console.error("API GET Error:", error);
      throw error; 
    }
  },

  // ADD THIS NEW POST METHOD
  post: async (endpoint, payload) => {
    try {
      const response = await fetch(`${BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload) // Convert Vue data to JSON
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      return { data }; 
    } catch (error) {
      console.error("API POST Error:", error);
      throw error;
    }
  }
};