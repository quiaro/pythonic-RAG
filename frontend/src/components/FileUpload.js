import React, { useState } from 'react';
import {
  Box,
  Button,
  Typography,
  Paper,
  CircularProgress,
  Alert,
  Fade,
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import api from '../utils/api';

const FileUpload = ({ setSessionId, setFileName, setStatus, status }) => {
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');

  const handleFileChange = (event) => {
    const selectedFile = event.target.files[0];

    if (!selectedFile) {
      setFile(null);
      return;
    }

    // Check file type
    const fileExtension = selectedFile.name.split('.').pop().toLowerCase();
    if (!['txt', 'pdf'].includes(fileExtension)) {
      setError('Only .txt and .pdf files are supported');
      setFile(null);
      return;
    }

    // Check file size (max 2MB)
    if (selectedFile.size > 2 * 1024 * 1024) {
      setError('File size must be less than 2MB');
      setFile(null);
      return;
    }

    setError('');
    setFile(selectedFile);
  };

  const handleUpload = async () => {
    if (!file) return;

    try {
      setStatus('uploading');
      const formData = new FormData();
      formData.append('file', file);

      const response = await api.post('/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      const { session_id } = response.data;
      setSessionId(session_id);
      setFileName(file.name);
      setStatus('processing');

      // Poll for session status
      pollSessionStatus(session_id);
    } catch (error) {
      console.error('Upload error:', error);
      setError(error.response?.data?.detail || 'Failed to upload file');
      setStatus('error');
    }
  };

  const pollSessionStatus = async (sessionId) => {
    try {
      const response = await api.get(`/session/${sessionId}`);
      if (response.data.status === 'ready') {
        setStatus('ready');
      } else if (response.data.status === 'error') {
        setError(
          response.data.error || 'An error occurred while processing the file'
        );
        setStatus('error');
      } else {
        // Still processing, poll again after 1 second
        setTimeout(() => pollSessionStatus(sessionId), 1000);
      }
    } catch (error) {
      console.error('Polling error:', error);

      if (error.response && error.response.status === 404) {
        // If we get a 404, the session may not be ready yet, try again after a delay
        setTimeout(() => pollSessionStatus(sessionId), 1000);
      } else {
        setError('Failed to check processing status');
        setStatus('error');
      }
    }
  };

  return (
    <Paper
      elevation={3}
      sx={{
        p: 4,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        minHeight: '70vh',
        justifyContent: 'center',
      }}
    >
      <Typography variant="h4" component="h1" gutterBottom>
        Chat with Your Files
      </Typography>

      <Typography variant="body1" sx={{ mb: 4, textAlign: 'center' }}>
        Upload a text or PDF file (max 2MB) and ask questions about its content
      </Typography>

      {status === 'uploading' || status === 'processing' ? (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <CircularProgress size={60} sx={{ mb: 2 }} />
          <Typography variant="h6">
            {status === 'uploading'
              ? 'Uploading file...'
              : 'Processing file...'}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            This may take a moment depending on the file size
          </Typography>
        </Box>
      ) : (
        <>
          <input
            type="file"
            id="file-upload"
            accept=".txt,.pdf"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
          <label htmlFor="file-upload">
            <Button
              component="span"
              variant="contained"
              startIcon={<CloudUploadIcon />}
              sx={{ mb: 2 }}
            >
              Select File
            </Button>
          </label>

          {file && (
            <Typography variant="body2" sx={{ mb: 2 }}>
              Selected file: {file.name}
            </Typography>
          )}

          <Button
            variant="contained"
            color="primary"
            disabled={
              !file || status === 'uploading' || status === 'processing'
            }
            onClick={handleUpload}
            sx={{ mt: 2 }}
          >
            Upload and Process
          </Button>
        </>
      )}

      <Fade in={!!error}>
        <Alert
          severity="error"
          sx={{ mt: 3, width: '100%' }}
          onClose={() => setError('')}
        >
          {error}
        </Alert>
      </Fade>
    </Paper>
  );
};

export default FileUpload;
