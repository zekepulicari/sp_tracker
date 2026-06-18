### Instructions

To use the Species Tracker application, follow these steps:

1. **Launch the Application**: Run the FastAPI server in the `backend` directory using `uvicorn main:app --reload` (or `python3 -m uvicorn main:app --reload`). 
2. **Open the Webpage**: Navigate your browser to `http://localhost:8000/`.
3. **Explore the Map**: 
   - Drag the map to explore global regions.
   - You will see a grid layer indicating the density of *Orcinus orca* observations.
4. **Zoom for Details**: 
   - Zoom in past the designated threshold (default: > 6) to transition from the grid layer to individual observation markers.
5. **View Sighting Info**:
   - Click on any specific marker to view details about that observation, including the date, photo, observer username, and location name.
6. **Future AI Assistant**:
   - The right-side panel is reserved for a future AI Assistant powered by Gemini. 

---

### Project Information

**iNaturalist API Reference**
The application relies on data from iNaturalist:
[https://api.inaturalist.org/v2/docs/#/Observations/get_observations](https://api.inaturalist.org/v2/docs/#/Observations/get_observations)

**Color Palette**
The visual design uses the following color palette:
- `#DAD7CD` (Light Background)
- `#A3B18A` (Light Accent)
- `#588157` (Primary Accent / Markers)
- `#3A5A40` (Dark Accent)
- `#344E41` (Dark Background / Text)
