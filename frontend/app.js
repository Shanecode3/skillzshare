let currentUser = null;
let isLoading = false;

const API_BASE = "https://skillzshare-backend.onrender.com";

/* -------------------------------
   API WRAPPER
---------------------------------- */
async function api(path, { method = 'GET', body = null, form = false } = {}) {
  const token = localStorage.getItem('token');
  const headers = form
    ? { 'Content-Type': 'application/x-www-form-urlencoded' }
    : { 'Content-Type': 'application/json' };

  if (token) headers['Authorization'] = `Bearer ${token}`;

  const url = `${API_BASE}${path}`;
  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body ? (form ? new URLSearchParams(body) : JSON.stringify(body)) : undefined,
    });
  } catch (e) {
    console.error('[API NETWORK ERROR]', method, url, e);
    throw new Error('Network error: could not reach backend.');
  }

  if (res.status === 204) return null;

  let data = {};
  try { data = await res.json(); } catch {}

  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      localStorage.removeItem('token');
      currentUser = null;
      updateUIForLogout();
      window.showPage('register');
    }
    throw new Error(data.detail || `${res.status} ${res.statusText}`);
  }
  return data;
}

function updateUIForLogout() {
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.style.display = 'none';
  
  // Hide protected nav buttons
  const protectedButtons = ['nav-profile', 'nav-matches', 'nav-collaborations', 'nav-messages'];
  protectedButtons.forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.style.display = 'none';
  });
  
  // Show register button
  const registerBtn = document.getElementById('nav-register');
  if (registerBtn) registerBtn.style.display = 'block';
}

function updateUIForLogin() {
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.style.display = 'block';
  
  // Show protected nav buttons
  const protectedButtons = ['nav-profile', 'nav-matches', 'nav-collaborations', 'nav-messages'];
  protectedButtons.forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.style.display = 'block';
  });
  
  // Optionally hide register button when logged in
  // const registerBtn = document.getElementById('nav-register');
  // if (registerBtn) registerBtn.style.display = 'none';
}

/* -------------------------------
   Helpers (skills)
---------------------------------- */
function slugify(name) {
  return name.toLowerCase().trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

function parseSkills(csv) {
  return csv.split(',').map(s => s.trim()).filter(Boolean);
}

async function findSkillByName(name) {
  const q = encodeURIComponent(name);
  const list = await api(`/skills/?q=${q}&only_active=true&limit=5`);
  const low = name.toLowerCase();
  return list.find(s =>
    s.name.toLowerCase() === low || s.slug === slugify(name)
  ) || null;
}

async function upsertSkill(name) {
  try {
    console.log('Upserting skill:', name);
    const existing = await findSkillByName(name);
    if (existing) {
      console.log('Skill exists:', existing);
      return existing;
    }

    console.log('Creating new skill:', name);
    const newSkill = await api('/skills/', {
      method: 'POST',
      body: {
        name: name,
        slug: slugify(name),
        category: 'General',
        synonyms_json: []
      }
    });
    console.log('Skill created:', newSkill);
    return newSkill;
  } catch (e) {
    console.error('Error in upsertSkill:', e);
    if (String(e.message).includes('409')) {
      console.log('409 conflict, trying to find existing skill');
      const found = await findSkillByName(name);
      if (found) {
        console.log('Found after 409:', found);
        return found;
      }
    }
    throw e;
  }
}

async function syncUserSkills(userId, newSkillNames) {
  const existing = await api(`/user-skills/?user_id=${userId}`);
  const existingNames = new Set(existing.map(s => s.skill_name?.toLowerCase()));
  const newNames = new Set(newSkillNames.map(n => n.toLowerCase()));

  // Remove skills no longer present
  for (const us of existing) {
    if (!newNames.has(us.skill_name?.toLowerCase())) {
      try {
        await api(`/user-skills/${userId}/${us.skill_id}`, { method: 'DELETE' });
      } catch (e) { console.warn('Delete user-skill error:', e); }
    }
  }

  // Add new skills
  for (const name of newSkillNames) {
    if (!existingNames.has(name.toLowerCase())) {
      try {
        const skill = await upsertSkill(name);
        await api('/user-skills/', {
          method: 'POST',
          body: { user_id: userId, skill_id: skill.id, level: 'intermediate', years_exp: 0.5, note: '' }
        });
      } catch (e) { 
        if (!String(e.message).includes('409')) console.warn('Add user-skill error:', e); 
      }
    }
  }
}

async function syncUserInterests(userId, newSkillNames) {
  const existing = await api(`/user-interests/?user_id=${userId}`);
  const existingNames = new Set(existing.map(s => s.skill_name?.toLowerCase()));
  const newNames = new Set(newSkillNames.map(n => n.toLowerCase()));

  // Remove interests no longer present
  for (const ui of existing) {
    if (!newNames.has(ui.skill_name?.toLowerCase())) {
      try {
        await api(`/user-interests/${userId}/${ui.skill_id}`, { method: 'DELETE' });
      } catch (e) { console.warn('Delete user-interest error:', e); }
    }
  }

  // Add new interests
  for (const name of newSkillNames) {
    if (!existingNames.has(name.toLowerCase())) {
      try {
        const skill = await upsertSkill(name);
        await api('/user-interests/', {
          method: 'POST',
          body: { user_id: userId, skill_id: skill.id, desired_level: 'intermediate', priority: 3, note: '' }
        });
      } catch (e) { 
        if (!String(e.message).includes('409')) console.warn('Add user-interest error:', e); 
      }
    }
  }
}

async function attachUserSkillsAndInterests({ userId, offeredCsv, wantedCsv }) {
  const offered = parseSkills(offeredCsv);
  const wanted  = parseSkills(wantedCsv);

  console.log('Attaching skills for user:', userId);
  console.log('Offered skills:', offered);
  console.log('Wanted skills:', wanted);

  // Process offered skills
  for (const skillName of offered) {
    try {
      console.log('Processing offered skill:', skillName);
      const skill = await upsertSkill(skillName);
      console.log('Skill upserted:', skill);
      
      const payload = {
        user_id: userId,
        skill_id: skill.id,
        level: 'intermediate',
        years_exp: 0.5,
        note: 'Added from signup'
      };
      console.log('Creating user-skill with payload:', payload);
      
      const result = await api('/user-skills/', {
        method: 'POST',
        body: payload
      });
      console.log('User-skill created:', result);
    } catch (e) {
      if (!String(e.message).includes('409')) {
        console.error('Error attaching offered skill:', skillName, e);
      } else {
        console.log('Skill already attached:', skillName);
      }
    }
  }

  // Process wanted skills
  for (const skillName of wanted) {
    try {
      console.log('Processing wanted skill:', skillName);
      const skill = await upsertSkill(skillName);
      console.log('Skill upserted:', skill);
      
      const payload = {
        user_id: userId,
        skill_id: skill.id,
        desired_level: 'intermediate',
        priority: 3,
        note: 'Added from signup'
      };
      console.log('Creating user-interest with payload:', payload);
      
      const result = await api('/user-interests/', {
        method: 'POST',
        body: payload
      });
      console.log('User-interest created:', result);
    } catch (e) {
      if (!String(e.message).includes('409')) {
        console.error('Error attaching wanted skill:', skillName, e);
      } else {
        console.log('Interest already attached:', skillName);
      }
    }
  }

  console.log('Finished attaching all skills');
}

async function loadUserSkillsAndInterests(userId) {
  try {
    const [userSkills, userInterests] = await Promise.all([
      api(`/user-skills/?user_id=${userId}`),
      api(`/user-interests/?user_id=${userId}`)
    ]);
    
    const offeredNames = userSkills.map(us => us.skill_name).filter(Boolean);
    const wantedNames = userInterests.map(ui => ui.skill_name).filter(Boolean);
    
    return {
      offered: offeredNames.join(', '),
      wanted: wantedNames.join(', ')
    };
  } catch (e) {
    console.error('Error loading skills:', e);
    return { offered: '', wanted: '' };
  }
}

/* -------------------------------
   Match Generation
---------------------------------- */
async function generateMatchCandidates(userId) {
  try {
    console.log('Generating match candidates for user:', userId);
    
    // Get user's skills (what they offer)
    const mySkills = await api(`/user-skills/?user_id=${userId}`);
    console.log('My skills:', mySkills);
    
    // Get user's interests (what they want)
    const myInterests = await api(`/user-interests/?user_id=${userId}`);
    console.log('My interests:', myInterests);
    
    if (mySkills.length === 0 || myInterests.length === 0) {
      console.log('User needs both skills and interests to generate matches');
      return;
    }
    
    // Get all other users
    const allUsers = await api('/users/?limit=100');
    const otherUsers = allUsers.filter(u => u.id !== userId && u.is_active);
    console.log('Found', otherUsers.length, 'other users');
    
    // Track created matches to avoid duplicates
    const createdMatches = new Set();
    
    for (const otherUser of otherUsers) {
      // Get their skills (what they offer)
      const theirSkills = await api(`/user-skills/?user_id=${otherUser.id}`);
      
      // Get their interests (what they want)
      const theirInterests = await api(`/user-interests/?user_id=${otherUser.id}`);
      
      // Find the BEST match between these two users
      let bestMatch = null;
      let bestScore = 0;
      
      // Find matches: I offer what they want, they offer what I want
      for (const mySkill of mySkills) {
        for (const theirInterest of theirInterests) {
          if (mySkill.skill_id === theirInterest.skill_id) {
            // They want what I offer
            for (const theirSkill of theirSkills) {
              for (const myInterest of myInterests) {
                if (theirSkill.skill_id === myInterest.skill_id) {
                  // I want what they offer - Perfect match!
                  const score = 8.5; // Base score for mutual match
                  
                  if (score > bestScore) {
                    bestScore = score;
                    bestMatch = {
                      offered_skill_id: mySkill.skill_id,
                      wanted_skill_id: theirSkill.skill_id,
                      offered_skill_name: mySkill.skill_name,
                      wanted_skill_name: theirSkill.skill_name
                    };
                  }
                }
              }
            }
          }
        }
      }
      
      // Only create ONE match candidate per user pair
      if (bestMatch) {
        const matchKey = `${userId}-${otherUser.id}`;
        
        if (!createdMatches.has(matchKey)) {
          createdMatches.add(matchKey);
          
          const rationale = `You can teach ${bestMatch.offered_skill_name}, they can teach ${bestMatch.wanted_skill_name}`;
          
          try {
            await api('/match-candidates/', {
              method: 'POST',
              body: {
                source_user_id: userId,
                target_user_id: otherUser.id,
                offered_skill_id: bestMatch.offered_skill_id,
                wanted_skill_id: bestMatch.wanted_skill_id,
                score: bestScore,
                rationale: rationale
              }
            });
            console.log(`✅ Created match candidate: ${userId} <-> ${otherUser.id}`);
          } catch (e) {
            if (!String(e.message).includes('409')) {
              console.warn('Error creating match candidate:', e);
            } else {
              console.log('⚠️ Match already exists');
            }
          }
        }
      }
    }
    
    console.log('Match generation complete');
  } catch (e) {
    console.error('Error generating matches:', e);
  }
}

/* -------------------------------
   Auth tabs
---------------------------------- */
window.showAuthTab = function(which) {
  const rTab = document.getElementById('tab-register');
  const lTab = document.getElementById('tab-login');
  const rPane = document.getElementById('register-pane');
  const lPane = document.getElementById('login-pane');

  if (!rTab || !lTab || !rPane || !lPane) return;

  if (which === 'register') {
    rTab.classList.add('active'); lTab.classList.remove('active');
    rPane.classList.add('active'); lPane.classList.remove('active');
  } else {
    lTab.classList.add('active'); rTab.classList.remove('active');
    lPane.classList.add('active'); rPane.classList.remove('active');
  }
};

/* -------------------------------
   Navigation
---------------------------------- */
window.showPage = function(pageName) {
  // Check authentication for protected pages
  const protectedPages = ['profile', 'matches', 'collaborations', 'messages'];
  
  if (protectedPages.includes(pageName) && !currentUser) {
    // Not logged in, redirect to register
    alert('Please login to access this page');
    pageName = 'register';
    window.showAuthTab('login');
  }

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));

  const pageEl = document.getElementById(pageName);
  const navBtn = document.getElementById('nav-' + pageName);
  if (pageEl) pageEl.classList.add('active');
  if (navBtn) navBtn.classList.add('active');

  if (pageName === 'profile') loadProfile();
  else if (pageName === 'matches') loadMatches();
  else if (pageName === 'messages') loadMessages();
  else if (pageName === 'collaborations') loadCollaborations();
  else if (pageName === 'register') {
    const params = new URLSearchParams(location.search);
    const tab = params.get('auth');
    if (tab === 'login') window.showAuthTab('login');
    else window.showAuthTab('register');
  }
};

/* -------------------------------
   Register
---------------------------------- */
window.handleRegister = async function(e) {
  e.preventDefault();
  if (isLoading) return;
  isLoading = true;

  const name = document.getElementById('name').value.trim();
  const email = document.getElementById('email').value.trim().toLowerCase();
  const password = document.getElementById('password').value.trim();
  const college = document.getElementById('college').value.trim();
  const skillsOffered = document.getElementById('skills_offered').value.trim();
  const skillsWanted = document.getElementById('skills_wanted').value.trim();
  const messageBox = document.getElementById('register-message');

  messageBox.innerHTML = `<div class="loading">Creating your account...</div>`;

  try {
    console.log('Step 1: Creating user...');
    // Create user
    const user = await api('/users/', {
      method: 'POST',
      body: { 
        email, 
        password, 
        full_name: name, 
        handle: email.split('@')[0]
      }
    });

    console.log('User created:', user);
    messageBox.innerHTML = `<div class="loading">Logging you in...</div>`;

    // Login to get token
    console.log('Step 2: Logging in...');
    const login = await api('/auth/login', {
      method: 'POST',
      body: { username: email, password },
      form: true,
    });
    
    console.log('Login successful, token received');
    localStorage.setItem('token', login.access_token);
    
    // Get full user details with token
    console.log('Step 3: Fetching user details...');
    const me = await api('/auth/me');
    currentUser = me;
    console.log('Current user set:', currentUser);
    updateUIForLogin();

    messageBox.innerHTML = `<div class="loading">Setting up your profile...</div>`;

    // Update institute if provided
    if (college) {
      try {
        console.log('Step 4: Updating institute...');
        await api(`/users/${currentUser.id}`, {
          method: 'PATCH',
          body: { institute: college }
        });
        console.log('Institute updated successfully');
      } catch (err) {
        console.warn('Could not update institute (non-fatal):', err.message);
        // Continue anyway - institute is not critical
      }
    }

    // Add skills and interests
    if (skillsOffered || skillsWanted) {
      console.log('Step 5: Adding skills...');
      messageBox.innerHTML = `<div class="loading">Adding your skills...</div>`;
      await attachUserSkillsAndInterests({ 
        userId: currentUser.id, 
        offeredCsv: skillsOffered, 
        wantedCsv: skillsWanted 
      });
      console.log('Skills attached successfully');
    }

    // Create match candidates for this user
    console.log('Step 6: Finding potential matches...');
    try {
      await generateMatchCandidates(currentUser.id);
    } catch (e) {
      console.warn('Could not generate matches yet:', e);
    }

    messageBox.innerHTML = `<div class="message success">✅ Registration successful! Redirecting to your profile...</div>`;
    setTimeout(() => {
      const form = document.getElementById('registerForm');
      if (form) form.reset();
      messageBox.innerHTML = '';
      window.showPage('profile');
      isLoading = false;
    }, 1500);
  } catch (err) {
    console.error('Registration error:', err);
    messageBox.innerHTML = `<div class="message error">❌ Registration failed: ${err.message}</div>`;
    isLoading = false;
  }
};

/* -------------------------------
   Login
---------------------------------- */
window.handleLogin = async function(e) {
  e.preventDefault();
  if (isLoading) return;
  isLoading = true;

  const email = document.getElementById('login-email').value.trim().toLowerCase();
  const password = document.getElementById('login-password').value.trim();
  const messageBox = document.getElementById('login-message');

  messageBox.innerHTML = `<div class="loading">Logging in...</div>`;

  try {
    console.log('Attempting login for:', email);
    
    const login = await api('/auth/login', { 
      method: 'POST', 
      body: { username: email, password }, 
      form: true 
    });
    
    console.log('Login successful, storing token');
    localStorage.setItem('token', login.access_token);

    console.log('Fetching user details...');
    const me = await api('/auth/me');
    currentUser = me;
    console.log('Current user:', currentUser);
    
    updateUIForLogin();

    messageBox.innerHTML = `<div class="message success">✅ Logged in successfully!</div>`;
    setTimeout(() => {
      const form = document.getElementById('loginForm');
      if (form) form.reset();
      messageBox.innerHTML = '';
      window.showPage('profile');
      isLoading = false;
    }, 800);
  } catch (err) {
    console.error('Login error:', err);
    messageBox.innerHTML = `<div class="message error">❌ Login failed: ${err.message}</div>`;
    isLoading = false;
  }
};

/* -------------------------------
   Profile
---------------------------------- */
async function loadProfile() {
  const message = document.getElementById('profile-message');
  
  if (!currentUser) {
    console.log('No current user, redirecting to login');
    if (message) message.innerHTML = `<div class="message error">Please login first.</div>`;
    setTimeout(() => window.showPage('register'), 500);
    return;
  }

  try {
    console.log('Loading profile for user:', currentUser.id);
    
    // Get fresh user data from /auth/me first
    const me = await api('/auth/me');
    currentUser = me;
    console.log('Fresh auth data:', me);

    // Get full user details from /users/{id}
    const userDetails = await api(`/users/${me.id}`);
    console.log('Full user details:', userDetails);
    
    document.getElementById('profile-name').value = userDetails.full_name || '';
    document.getElementById('profile-email').value = userDetails.email || '';
    document.getElementById('profile-college').value = userDetails.institute || '';
    document.getElementById('profile-email').setAttribute('readonly', 'readonly');

    // Load skills and interests
    console.log('Loading skills and interests...');
    const { offered, wanted } = await loadUserSkillsAndInterests(me.id);
    console.log('Skills loaded:', { offered, wanted });
    
    document.getElementById('profile-skills-offered').value = offered;
    document.getElementById('profile-skills-wanted').value = wanted;
    
    if (message) message.innerHTML = '';
  } catch (err) {
    console.error('Profile load error:', err);
    if (message) {
      message.innerHTML = `<div class="message error">Error loading profile: ${err.message}<br>Please try logging in again.</div>`;
    }
    
    // If unauthorized, redirect to login
    if (err.message.includes('401') || err.message.includes('403') || err.message.includes('Invalid')) {
      setTimeout(() => {
        localStorage.removeItem('token');
        currentUser = null;
        updateUIForLogout();
        window.showPage('register');
      }, 2000);
    }
  }
}

window.handleProfileUpdate = async function(e) {
  e.preventDefault();
  if (isLoading) return;
  isLoading = true;

  const body = {
    full_name: document.getElementById('profile-name').value.trim(),
    institute: document.getElementById('profile-college').value.trim(),
  };

  const offeredCsv = document.getElementById('profile-skills-offered').value.trim();
  const wantedCsv = document.getElementById('profile-skills-wanted').value.trim();
  const messageEl = document.getElementById('profile-message');

  try {
    messageEl.innerHTML = `<div class="loading">Updating profile...</div>`;
    
    await api(`/users/${currentUser.id}`, { method: 'PATCH', body });
    
    messageEl.innerHTML = `<div class="loading">Updating skills...</div>`;
    await syncUserSkills(currentUser.id, parseSkills(offeredCsv));
    await syncUserInterests(currentUser.id, parseSkills(wantedCsv));
    
    messageEl.innerHTML = `<div class="loading">Regenerating matches...</div>`;
    await generateMatchCandidates(currentUser.id);
    
    messageEl.innerHTML = `<div class="message success">✅ Profile updated successfully!</div>`;
    
    setTimeout(() => {
      messageEl.innerHTML = '';
    }, 3000);
  } catch (err) {
    console.error('Profile update error:', err);
    messageEl.innerHTML = `<div class="message error">❌ Update failed: ${err.message}</div>`;
  } finally {
    isLoading = false;
  }
};

/* -------------------------------
   Matches
---------------------------------- */
const skillCache = new Map();
async function getSkill(id) {
  if (!id) return null;
  if (skillCache.has(id)) return skillCache.get(id);
  try {
    const s = await api(`/skills/${id}`);
    skillCache.set(id, s);
    return s;
  } catch (e) {
    console.error('Error fetching skill:', id, e);
    return null;
  }
}

const userCache = new Map();
async function getUser(id) {
  if (userCache.has(id)) return userCache.get(id);
  try {
    const u = await api(`/users/${id}`);
    userCache.set(id, u);
    return u;
  } catch (e) {
    console.error('Error fetching user:', id, e);
    return null;
  }
}

async function loadMatches() {
  const box = document.getElementById('matches-list');
  box.innerHTML = `<div class="loading">Finding your matches...</div>`;
  
  if (!currentUser) {
    box.innerHTML = `<div class="message error">Please login to see matches.</div>`;
    return;
  }
  
  try {
    console.log('Loading matches for user:', currentUser.id);
    
    // First, try to generate fresh matches
    await generateMatchCandidates(currentUser.id);
    
    // Then fetch match candidates
    const candidates = await api(`/match-candidates/?source_user_id=${currentUser.id}&limit=50`);
    console.log('Found', candidates.length, 'match candidates');
    
    if (!candidates.length) {
      box.innerHTML = `
        <div class="card">
          <h3>No matches yet</h3>
          <p>To find matches:</p>
          <ul style="margin-left: 20px; margin-top: 10px;">
            <li>Make sure you've added skills you offer in your profile</li>
            <li>Make sure you've added skills you want to learn</li>
            <li>Wait for other users to register with complementary skills</li>
          </ul>
          <p style="margin-top: 15px;">We'll automatically match you with users who:</p>
          <ul style="margin-left: 20px; margin-top: 10px;">
            <li>Want to learn skills you offer</li>
            <li>Offer skills you want to learn</li>
          </ul>
        </div>`;
      return;
    }

    // Deduplicate by target_user_id - keep only the best match per user
    const uniqueMatches = new Map();
    candidates.forEach(m => {
      const existing = uniqueMatches.get(m.target_user_id);
      if (!existing || m.score > existing.score) {
        uniqueMatches.set(m.target_user_id, m);
      }
    });
    
    console.log('Unique matches after deduplication:', uniqueMatches.size);

    const rows = await Promise.all([...uniqueMatches.values()].map(async m => {
      const target = await getUser(m.target_user_id);
      const offered = m.offered_skill_id ? await getSkill(m.offered_skill_id) : null;
      const wanted  = m.wanted_skill_id  ? await getSkill(m.wanted_skill_id)  : null;
      
      if (!target) return '';
      
      const targetName = target.full_name || target.handle || target.email || `User ${m.target_user_id}`;
      const targetHandle = target.handle || target.email || '';
      const targetInstitute = target.institute || '';
      
      return `
        <div class="card match-card">
          <h3>🎯 ${m.rationale || 'Potential Match'}</h3>
          <div style="margin: 15px 0;">
            <p><strong>👤 Match:</strong> ${targetName}${targetHandle ? ` (@${targetHandle})` : ''}</p>
            ${targetInstitute ? `<p><strong>🏫 Institute:</strong> ${targetInstitute}</p>` : ''}
          </div>
          <div style="background: rgba(0, 191, 255, 0.1); padding: 15px; border-radius: 10px; margin: 15px 0;">
            <p><strong>📚 You teach:</strong> <span style="color: #00ff00;">${offered ? offered.name : '—'}</span></p>
            <p><strong>📖 They teach:</strong> <span style="color: #00bfff;">${wanted ? wanted.name : '—'}</span></p>
          </div>
          <p><strong>⭐ Match Score:</strong> ${Number(m.score || 0).toFixed(1)}/10</p>
          <button class="btn-primary" onclick="window.sendCollabRequest(${m.target_user_id}, ${m.offered_skill_id}, ${m.wanted_skill_id})" style="margin-top: 15px; width: 100%;">
            📨 Send Collaboration Request
          </button>
        </div>
      `;
    }));
    
    const validRows = rows.filter(r => r);
    if (validRows.length > 0) {
      box.innerHTML = validRows.join('');
    } else {
      box.innerHTML = `<p style="text-align:center;color:#87ceeb;margin-top:20px;">No valid matches found.</p>`;
    }
  } catch (err) {
    console.error('Error loading matches:', err);
    box.innerHTML = `<div class="message error">Error loading matches: ${err.message}</div>`;
  }
}

/* -------------------------------
   Collaborations
---------------------------------- */
async function loadCollaborations() {
  const box = document.getElementById('collab-list');
  box.innerHTML = `<div class="loading">Loading collaborations...</div>`;
  
  if (!currentUser) {
    box.innerHTML = `<div class="message error">Please login to see collaborations.</div>`;
    return;
  }
  
  try {
    const requests = await api(`/collab-requests/?user_id=${currentUser.id}&limit=50`);
    console.log('Loaded collaboration requests:', requests);
    
    if (!requests.length) {
      box.innerHTML = `<p style="text-align:center;color:#87ceeb;margin-top:20px;">No collaboration requests yet.</p>`;
      return;
    }

    const rows = await Promise.all(requests.map(async req => {
      const isRequester = req.requester_id === currentUser.id;
      const otherId = isRequester ? req.receiver_id : req.requester_id;
      const other = await getUser(otherId);
      const otherName = other?.full_name || other?.handle || 'Unknown';
      
      const offered = req.offered_skill_id ? await getSkill(req.offered_skill_id) : null;
      const wanted = req.wanted_skill_id ? await getSkill(req.wanted_skill_id) : null;

      let actions = '';
      if (req.status === 'PENDING' && !isRequester) {
        actions = `
          <button class="btn-success" onclick="window.updateCollabStatus(${req.id}, 'ACCEPTED')">Accept</button>
          <button class="btn-danger" onclick="window.updateCollabStatus(${req.id}, 'DECLINED')">Decline</button>
        `;
      } else if (req.status === 'PENDING' && isRequester) {
        actions = `<button class="btn-danger" onclick="window.updateCollabStatus(${req.id}, 'CANCELLED')">Cancel</button>`;
      } else if (req.status === 'ACCEPTED') {
        actions = `
          <button class="btn-success" onclick="window.updateCollabStatus(${req.id}, 'COMPLETED')">Mark Complete</button>
          <button class="btn-danger" onclick="window.updateCollabStatus(${req.id}, 'CANCELLED')">Cancel</button>
        `;
      }

      const statusBadge = `<span class="status-${req.status.toLowerCase()}">${req.status}</span>`;

      // Only show message button if status is ACCEPTED (active collaboration)
      const messageButton = req.status === 'ACCEPTED' 
        ? `<button class="btn-secondary" onclick="event.preventDefault(); window.openChatFromCollab(${otherId}, '${otherName.replace(/'/g, "\\'")}')">💬 Message</button>`
        : '';

      return `
        <div class="card collab-card">
          <div class="collab-header">
            <h3>${isRequester ? 'To' : 'From'}: ${otherName}</h3>
            ${statusBadge}
          </div>
          ${req.message ? `<p><em>"${req.message}"</em></p>` : ''}
          <p><strong>Exchange:</strong> ${offered?.name || '—'} ↔ ${wanted?.name || '—'}</p>
          ${req.scheduled_at ? `<p><strong>Scheduled:</strong> ${new Date(req.scheduled_at).toLocaleString()}</p>` : ''}
          <p><strong>Created:</strong> ${new Date(req.created_at).toLocaleString()}</p>
          <div class="collab-actions">
            ${actions}
            ${messageButton}
          </div>
        </div>
      `;
    }));
    
    box.innerHTML = rows.join('');
  } catch (err) {
    console.error('Error loading collaborations:', err);
    box.innerHTML = `<div class="message error">${err.message || 'Could not load collaborations.'}</div>`;
  }
}

window.openChatFromCollab = function(partnerId, partnerName) {
  console.log('Opening chat with:', partnerId, partnerName);
  // Switch to messages page
  window.showPage('messages');
  // Wait a bit for messages page to load, then open chat
  setTimeout(() => {
    window.openChat(partnerId);
  }, 500);
};

window.sendCollabRequest = async function(targetUserId, offeredSkillId, wantedSkillId) {
  const message = prompt('Add a message to your collaboration request (optional):');
  
  try {
    await api('/collab-requests/', {
      method: 'POST',
      body: {
        requester_id: currentUser.id,
        receiver_id: targetUserId,
        offered_skill_id: offeredSkillId,
        wanted_skill_id: wantedSkillId,
        message: message || ''
      }
    });
    
    alert('Collaboration request sent successfully!');
    window.showPage('collaborations');
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
};

window.updateCollabStatus = async function(requestId, newStatus) {
  try {
    await api(`/collab-requests/${requestId}/status`, {
      method: 'POST',
      body: {
        actor_user_id: currentUser.id,
        new_status: newStatus
      }
    });
    
    loadCollaborations();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
};

/* -------------------------------
   Messages
---------------------------------- */
let activeChat = null;
let messageInterval = null;

async function loadMessages() {
  const box = document.getElementById('messages-container');
  
  if (!currentUser) {
    box.innerHTML = `<div class="message error">Please login to view messages.</div>`;
    return;
  }
  
  box.innerHTML = `<div class="loading">Loading conversations...</div>`;
  
  try {
    console.log('Loading messages for user:', currentUser.id);
    
    // Get accepted collaborations to determine who we can chat with
    const collabs = await api(`/collab-requests/?user_id=${currentUser.id}&status=ACCEPTED&limit=100`);
    
    if (!collabs || collabs.length === 0) {
      box.innerHTML = `
        <div style="text-align:center;color:#87ceeb;margin-top:100px;">
          <h3>No active collaborations</h3>
          <p>Accept a collaboration request first to start messaging!</p>
          <button class="btn-primary" onclick="window.showPage('collaborations')" style="margin-top: 20px;">
            View Collaboration Requests
          </button>
        </div>
      `;
      return;
    }
    
    // Get all messages where user is sender or receiver
    const [sent, received] = await Promise.all([
      api(`/messages/?sender_id=${currentUser.id}&limit=200`),
      api(`/messages/?receiver_id=${currentUser.id}&limit=200`)
    ]);
    
    console.log('Sent messages:', sent.length);
    console.log('Received messages:', received.length);
    
    // Build list of collaboration partners (people we have ACCEPTED collabs with)
    const collabPartners = new Set();
    collabs.forEach(c => {
      const otherId = c.requester_id === currentUser.id ? c.receiver_id : c.requester_id;
      collabPartners.add(otherId);
    });
    
    console.log('Collaboration partners:', Array.from(collabPartners));
    
    // Create conversations only for collab partners
    const conversations = await Promise.all([...collabPartners].map(async partnerId => {
      const partner = await getUser(partnerId);
      const msgs = [...sent, ...received]
        .filter(m => m.sender_id === partnerId || m.receiver_id === partnerId)
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
      
      const lastMsg = msgs[0];
      const unread = msgs.filter(m => m.receiver_id === currentUser.id && !m.is_read).length;
      
      return {
        partnerId,
        partnerName: partner?.full_name || partner?.handle || 'Unknown User',
        lastMessage: lastMsg ? lastMsg.body.substring(0, 50) + (lastMsg.body.length > 50 ? '...' : '') : 'No messages yet',
        lastTime: lastMsg ? new Date(lastMsg.created_at) : new Date(0),
        unread,
        hasMessages: msgs.length > 0
      };
    }));

    conversations.sort((a, b) => b.lastTime - a.lastTime);

    const listHtml = conversations.map(conv => `
      <div class="conversation-item" onclick="window.openChat(${conv.partnerId})">
        <div class="conv-info">
          <strong>${conv.partnerName}</strong>
          ${conv.unread > 0 ? `<span class="unread-badge">${conv.unread}</span>` : ''}
        </div>
        <div class="conv-preview">${escapeHtml(conv.lastMessage)}</div>
        <div class="conv-time">${conv.hasMessages ? formatTime(conv.lastTime) : 'Start chatting'}</div>
      </div>
    `).join('');

    box.innerHTML = `
      <div class="messages-sidebar">
        <h3>Active Collaborations</h3>
        ${listHtml}
      </div>
      <div class="messages-chat" id="chat-area">
        <p style="text-align:center;color:#87ceeb;margin-top:100px;">Select a conversation to start messaging</p>
      </div>
    `;
  } catch (err) {
    console.error('Error loading messages:', err);
    box.innerHTML = `<div class="message error">Error loading messages: ${err.message}</div>`;
  }
}

window.openChat = async function(partnerId) {
  activeChat = partnerId;
  
  // Check if there are any messages in this thread
  try {
    const thread = await api(`/messages/thread?user_a=${currentUser.id}&user_b=${partnerId}&limit=1`);
    
    // If no messages exist, send a welcome message automatically
    if (!thread || thread.length === 0) {
      const partner = await getUser(partnerId);
      const partnerName = partner?.full_name || partner?.handle || 'there';
      
      await api('/messages/', {
        method: 'POST',
        body: {
          sender_id: currentUser.id,
          receiver_id: partnerId,
          body: `Hi ${partnerName}! I'm excited to start our skill exchange. When would be a good time for you?`
        }
      });
    }
  } catch (e) {
    console.warn('Error checking/creating initial message:', e);
  }
  
  // Mark messages as read
  try {
    await api(`/messages/mark-read?user_id=${currentUser.id}&from_user_id=${partnerId}`, { method: 'POST' });
  } catch (e) { console.warn('Mark read error:', e); }
  
  await renderChat(partnerId, false);
  
  // Auto-refresh messages every 3 seconds - but only update messages, not entire chat
  if (messageInterval) clearInterval(messageInterval);
  messageInterval = setInterval(() => {
    if (activeChat === partnerId) {
      updateChatMessages(partnerId);
    }
  }, 3000);
};

async function updateChatMessages(partnerId) {
  // Only update the messages div, not the entire chat
  try {
    const thread = await api(`/messages/thread?user_a=${currentUser.id}&user_b=${partnerId}&limit=100`);
    const msgDiv = document.getElementById('chat-messages');
    if (!msgDiv) return;
    
    const messagesHtml = thread.map(msg => {
      const isMine = msg.sender_id === currentUser.id;
      return `
        <div class="message-bubble ${isMine ? 'mine' : 'theirs'}">
          <div class="msg-body">${escapeHtml(msg.body)}</div>
          <div class="msg-time">${new Date(msg.created_at).toLocaleTimeString()}</div>
        </div>
      `;
    }).join('');
    
    // Only update if content changed
    const newContent = messagesHtml || '<p style="text-align:center;color:#87ceeb;">No messages yet. Start the conversation!</p>';
    if (msgDiv.innerHTML !== newContent) {
      const wasAtBottom = msgDiv.scrollHeight - msgDiv.scrollTop <= msgDiv.clientHeight + 50;
      msgDiv.innerHTML = newContent;
      if (wasAtBottom) {
        msgDiv.scrollTop = msgDiv.scrollHeight;
      }
    }
  } catch (e) {
    console.warn('Error updating messages:', e);
  }
}

async function renderChat(partnerId, silent = false) {
  const chatArea = document.getElementById('chat-area');
  if (!chatArea) return;
  
  try {
    const partner = await getUser(partnerId);
    const thread = await api(`/messages/thread?user_a=${currentUser.id}&user_b=${partnerId}&limit=100`);
    
    const messagesHtml = thread.map(msg => {
      const isMine = msg.sender_id === currentUser.id;
      return `
        <div class="message-bubble ${isMine ? 'mine' : 'theirs'}">
          <div class="msg-body">${escapeHtml(msg.body)}</div>
          <div class="msg-time">${new Date(msg.created_at).toLocaleTimeString()}</div>
        </div>
      `;
    }).join('');

    chatArea.innerHTML = `
      <div class="chat-header">
        <h3>Chat with ${partner?.full_name || partner?.handle}</h3>
        <button class="btn-secondary" onclick="window.closeChat()">✕</button>
      </div>
      <div class="chat-messages" id="chat-messages">${messagesHtml || '<p style="text-align:center;color:#87ceeb;">No messages yet. Start the conversation!</p>'}</div>
      <div class="chat-input">
        <textarea id="msg-input" placeholder="Type your message... (Ctrl+Enter to send)" rows="2" onkeydown="if((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); window.sendMessage(${partnerId}); }"></textarea>
        <button class="btn-primary" onclick="window.sendMessage(${partnerId})">Send</button>
      </div>
    `;

    if (!silent) {
      const msgDiv = document.getElementById('chat-messages');
      if (msgDiv) msgDiv.scrollTop = msgDiv.scrollHeight;
    }
  } catch (err) {
    chatArea.innerHTML = `<div class="message error">${err.message}</div>`;
  }
}

window.sendMessage = async function(receiverId) {
  const input = document.getElementById('msg-input');
  const body = input.value.trim();
  if (!body) return;
  
  try {
    await api('/messages/', {
      method: 'POST',
      body: {
        sender_id: currentUser.id,
        receiver_id: receiverId,
        body
      }
    });
    
    input.value = '';
    await renderChat(receiverId);
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
};

window.closeChat = function() {
  if (messageInterval) clearInterval(messageInterval);
  activeChat = null;
  loadMessages();
};

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(date) {
  const now = new Date();
  const diff = now - date;
  
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return date.toLocaleDateString();
}

/* -------------------------------
   Logout
---------------------------------- */
window.handleLogout = function() {
  localStorage.removeItem('token');
  currentUser = null;
  updateUIForLogout();
  if (messageInterval) clearInterval(messageInterval);
  window.showPage('home');
};

/* -------------------------------
   Init
---------------------------------- */
async function initializeApp() {
  // Hide protected pages initially
  updateUIForLogout();
  
  try {
    const token = localStorage.getItem('token');
    if (token) {
      console.log('Token found, attempting to authenticate...');
      const me = await api('/auth/me');
      currentUser = me;
      console.log('Authenticated as:', currentUser);
      updateUIForLogin();
      window.showPage('profile');
    } else {
      console.log('No token found');
      window.showPage('home');
    }
  } catch (err) {
    console.error('Init error:', err);
    localStorage.removeItem('token');
    currentUser = null;
    updateUIForLogout();
    window.showPage('home');
  } finally {
    setTimeout(() => {
      const preloader = document.getElementById('preloader');
      if (preloader) preloader.classList.add('hidden');
    }, 1200);
  }
}

// Debug function - call from console
window.debugSkills = async function(userId) {
  console.log('=== DEBUG SKILLS FOR USER', userId, '===');
  
  try {
    const userSkills = await api(`/user-skills/?user_id=${userId}`);
    console.log('User Skills (offered):', userSkills);
    
    const userInterests = await api(`/user-interests/?user_id=${userId}`);
    console.log('User Interests (wanted):', userInterests);
    
    const allSkills = await api('/skills/?limit=100');
    console.log('All Skills in database:', allSkills);
    
    return { userSkills, userInterests, allSkills };
  } catch (e) {
    console.error('Debug error:', e);
  }
};

// Test skill attachment - call from console
window.testSkillAttachment = async function() {
  if (!currentUser) {
    console.error('Not logged in!');
    return;
  }
  
  console.log('=== TESTING SKILL ATTACHMENT ===');
  console.log('Current user:', currentUser);
  
  // Test creating a skill
  try {
    const testSkill = await api('/skills/', {
      method: 'POST',
      body: {
        name: 'Test Skill ' + Date.now(),
        slug: 'test-skill-' + Date.now(),
        category: 'General',
        synonyms_json: []
      }
    });
    console.log('✅ Test skill created:', testSkill);
    
    // Test attaching to user
    const userSkill = await api('/user-skills/', {
      method: 'POST',
      body: {
        user_id: currentUser.id,
        skill_id: testSkill.id,
        level: 'intermediate',
        years_exp: 1.0,
        note: 'Test'
      }
    });
    console.log('✅ User skill attached:', userSkill);
    
    // Test creating interest
    const userInterest = await api('/user-interests/', {
      method: 'POST',
      body: {
        user_id: currentUser.id,
        skill_id: testSkill.id,
        desired_level: 'advanced',
        priority: 5,
        note: 'Test interest'
      }
    });
    console.log('✅ User interest attached:', userInterest);
    
    console.log('=== ALL TESTS PASSED ===');
    return { testSkill, userSkill, userInterest };
  } catch (e) {
    console.error('❌ Test failed:', e);
    throw e;
  }
};

// Debug function - call from console
window.debugMessages = async function() {
  console.log('=== DEBUG MESSAGES ===');
  console.log('Current user:', currentUser);
  
  if (!currentUser) {
    console.error('Not logged in!');
    return;
  }
  
  try {
    const sent = await api(`/messages/?sender_id=${currentUser.id}&limit=200`);
    console.log(`Messages SENT by user ${currentUser.id}:`, sent);
    
    const received = await api(`/messages/?receiver_id=${currentUser.id}&limit=200`);
    console.log(`Messages RECEIVED by user ${currentUser.id}:`, received);
    
    const allMessages = [...sent, ...received];
    console.log('Total messages:', allMessages.length);
    
    // Find partners
    const partners = new Set();
    allMessages.forEach(msg => {
      const otherId = msg.sender_id === currentUser.id ? msg.receiver_id : msg.sender_id;
      partners.add(otherId);
    });
    
    console.log('Conversation partners:', Array.from(partners));
    
    return { sent, received, partners: Array.from(partners) };
  } catch (e) {
    console.error('Error:', e);
  }
};

// Test message sending - call from console
window.testMessage = async function(receiverId, messageText = 'Test message') {
  if (!currentUser) {
    console.error('Not logged in!');
    return;
  }
  
  if (receiverId === currentUser.id) {
    console.error('❌ Cannot send message to yourself!');
    console.log('💡 First, find other users:');
    console.log('   const users = await api("/users/?limit=20");');
    console.log('   console.log(users);');
    console.log('   Then use: await testMessage(OTHER_USER_ID, "Hello!");');
    return;
  }
  
  console.log('=== TESTING MESSAGE SEND ===');
  console.log('From:', currentUser.id);
  console.log('To:', receiverId);
  console.log('Message:', messageText);
  
  try {
    const result = await api('/messages/', {
      method: 'POST',
      body: {
        sender_id: currentUser.id,
        receiver_id: receiverId,
        body: messageText
      }
    });
    console.log('✅ Message sent:', result);
    return result;
  } catch (e) {
    console.error('❌ Error sending message:', e);
    throw e;
  }
};

// Helper to list other users
window.listUsers = async function() {
  console.log('=== ALL USERS ===');
  const users = await api('/users/?limit=50');
  const others = users.filter(u => u.id !== currentUser.id);
  
  console.log('You are:', currentUser.id, '-', currentUser.full_name);
  console.log('\nOther users:');
  others.forEach(u => {
    console.log(`  ID: ${u.id} - ${u.full_name} (${u.email})`);
  });
  
  if (others.length > 0) {
    console.log(`\n💡 To send a message, use: await testMessage(${others[0].id}, "Hello!")`);
  }
  
  return others;
};

initializeApp();