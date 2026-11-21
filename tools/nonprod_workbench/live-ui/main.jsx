import React from 'react';
import {createRoot} from 'react-dom/client';
import LiveApp from './app.jsx';
import '../daily-ui/style.css';
import './style.css';
createRoot(document.getElementById('root')).render(<LiveApp/>);
